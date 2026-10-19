"""Servicio de control: recibe lecturas del nodo ESP32 por MQTT, las guarda y
aplica las reglas de control sobre los actuadores reales.

Corre como proceso separado del dashboard: si la web se cae, el control sigue.

Uso:
    pip install paho-mqtt tinytuya
    python manage.py servicio_control --broker localhost --sala 1

Mensaje esperado del nodo (tópico invernadero/<sala_id>/lecturas, JSON):
    {"temperatura": 25.3, "humedad": 62.1, "co2": 540, "temp_hoja": 24.1,
     "luz": 41000, "ph": 6.02, "ec": 1.45, "temp_solucion": 20.4}
"""
import json
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from cultivo.models import VARIABLES, AccionActuador, Alerta, Lectura, Sala
from nucleo.controlador import ControladorClima
from nucleo.drivers import ErrorDriver, crear_driver
from nucleo.reglas import Rango, nivel_a_extractores
from nucleo.vpd import vpd_hoja

log = logging.getLogger("control")


class Command(BaseCommand):
    help = "Servicio de control en lazo cerrado (MQTT + reglas + drivers)."

    def add_arguments(self, parser):
        parser.add_argument("--broker", default="localhost")
        parser.add_argument("--puerto", type=int, default=1883)
        parser.add_argument("--sala", type=int, required=True)

    def handle(self, *args, **o):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.stderr.write("Falta instalar paho-mqtt: pip install paho-mqtt")
            return
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        self.sala = Sala.objects.get(pk=o["sala"])
        self.controlador = ControladorClima()
        self.ultimo_momento = None
        topico = f"invernadero/{self.sala.id}/lecturas"

        cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        cliente.on_connect = lambda c, u, f, rc, p=None: (c.subscribe(topico), log.info("Suscripto a %s", topico))
        cliente.on_message = self._mensaje
        cliente.connect(o["broker"], o["puerto"])
        log.info("Servicio de control de '%s' iniciado", self.sala)
        cliente.loop_forever()

    def _mensaje(self, cliente, userdata, msg):
        try:
            datos = json.loads(msg.payload)
        except json.JSONDecodeError:
            log.warning("Mensaje inválido: %r", msg.payload[:100])
            return
        ahora = timezone.now()
        if "temperatura" in datos and "humedad" in datos:
            datos["vpd"] = vpd_hoja(datos["temperatura"], datos["humedad"], datos.get("temp_hoja"))
        Lectura.objects.bulk_create([
            Lectura(sala=self.sala, variable=k, valor=float(v), momento=ahora, origen="sensor")
            for k, v in datos.items() if k in VARIABLES
        ])
        self._controlar(datos, ahora)
        # Foto diaria para el time-lapse (como mucho una consulta por minuto)
        if not getattr(self, "_ultima_revision_fotos", None) or (ahora - self._ultima_revision_fotos).total_seconds() >= 60:
            self._ultima_revision_fotos = ahora
            from cultivo.fotos import sacar_fotos_diarias
            for foto in sacar_fotos_diarias(ahora, self.sala)[0]:
                log.info("Foto diaria guardada: %s", foto)

    def _controlar(self, datos, ahora):
        self.sala.refresh_from_db(fields=["control_pausado"])
        if self.sala.control_pausado:
            return  # el usuario pausó el control: solo se mide y se registra
        periodo = self.sala.periodo_activo(ahora)
        if periodo and periodo.modo == "horario":
            return  # línea base: los interruptores siguen su programación horaria
        ciclo = self.sala.ciclo_activo()
        etapa = ciclo.etapa_en(ahora) if ciclo else None
        if not etapa or "vpd" not in datos:
            return
        rv, rt = etapa.rango("vpd"), etapa.rango("temperatura")
        if not rv or not rt:
            return

        minutos = (ahora - self.ultimo_momento).total_seconds() / 60 if self.ultimo_momento else 0
        self.ultimo_momento = ahora
        ext = self.sala.lecturas.filter(variable="temp_exterior").order_by("-momento").first()
        hr_ext = self.sala.lecturas.filter(variable="humedad_exterior").order_by("-momento").first()
        rh = etapa.rango("humedad")
        humid = self.sala.actuadores.filter(activo=True, tipo="humidificador").first()
        deshum = self.sala.actuadores.filter(activo=True, tipo="deshumidificador").first()
        salida = self.controlador.evaluar(
            datos["temperatura"], datos["humedad"], datos["vpd"], Rango(*rv), Rango(*rt), minutos,
            ext.valor if ext else None, hr_ext.valor if hr_ext else None,
            rango_hr=Rango(*rh) if rh else None,
            tiene_humidificador=bool(humid), tiene_deshumidificador=bool(deshum),
        )

        extractores = list(self.sala.actuadores.filter(activo=True, tipo="extractor").order_by("orden"))
        deseados = list(zip(extractores, nivel_a_extractores(salida.nivel_extraccion, len(extractores))))
        calef = self.sala.actuadores.filter(activo=True, tipo="calefactor").first()
        if calef:
            deseados.append((calef, salida.calefactor))
        if humid:
            deseados.append((humid, salida.humidificador))
        if deshum:
            deseados.append((deshum, salida.deshumidificador))
        # Ventiladores internos: circulación de aire continua mientras el control está activo
        deseados += [(v, True) for v in self.sala.actuadores.filter(activo=True, tipo="ventilador")]

        for actuador, encender in deseados:
            actuador.revisar_vencimiento(ahora)
            if actuador.modo != "auto" or actuador.encendido == encender:
                continue
            motivo = {"calefactor": salida.motivo_calefactor, "humidificador": salida.motivo_humedad,
                      "deshumidificador": salida.motivo_humedad,
                      "ventilador": "circulación de aire continua"}.get(actuador.tipo, salida.motivo_extraccion)
            try:
                crear_driver(actuador.driver, actuador.config).aplicar(encender)
            except ErrorDriver as exc:
                Alerta.objects.create(sala=self.sala, momento=ahora, nivel="critica",
                                      mensaje=f"{actuador.nombre} no responde: {exc}")
                log.error("%s no responde: %s", actuador, exc)
                continue
            actuador.encendido = encender
            actuador.save(update_fields=["encendido", "actualizado"])
            AccionActuador.objects.create(actuador=actuador, momento=ahora, encendido=encender,
                                          origen="automatico", motivo=motivo)
            log.info("%s -> %s (%s)", actuador, "ON" if encender else "OFF", motivo)
