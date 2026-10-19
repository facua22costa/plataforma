"""Genera datos SIMULADOS para desarrollar y demostrar la plataforma sin hardware.

Uso:
    python manage.py simular --reset              # crea la demo con 28 días de historial
    python manage.py simular --reset --dias 40 --cambio 20
    python manage.py simular --vivo               # sigue generando lecturas en tiempo real

El historial tiene dos períodos: control por horario (línea base) y control en
lazo cerrado, usando el mismo motor de reglas que el servicio de control real.
"""
import random
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from cultivo.models import (
    Camara,
    AccionActuador, Actuador, Alerta, EventoBitacora, Lectura, PeriodoExperimento, Receta, Sala,
)
from cultivo.fotos import crecimiento_del_ciclo, guardar_foto_diaria, sacar_fotos_diarias, svg_demo
from cultivo.servicios import crear_ciclo_desde_catalogo
from nucleo.controlador import ControladorClima
from nucleo.reglas import Rango, nivel_a_extractores
from nucleo.simulacion import (
    ClimaExterior, ModeloInvernadero, calefactor_por_horario,
    extractores_por_horario, luces_encendidas,
)  # extractores_por_horario se usa en modo vivo
from nucleo.vpd import humedad_absoluta

PASO_MIN = 5

VARIABLES_GUARDADAS = ["temperatura", "humedad", "vpd", "co2", "temp_hoja", "luz", "ph", "ec",
                       "temp_solucion", "temp_exterior", "humedad_exterior"]


class Command(BaseCommand):
    help = "Genera datos simulados de un invernadero (historial y/o en vivo)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Borra la demo y la vuelve a crear")
        parser.add_argument("--dias", type=int, default=28, help="Días de historial a generar")
        parser.add_argument("--cambio", type=int, default=14, help="Día en que empieza el lazo cerrado")
        parser.add_argument("--vivo", action="store_true", help="Generar lecturas en tiempo real")
        parser.add_argument("--intervalo", type=float, default=10, help="Segundos entre lecturas en vivo")
        parser.add_argument("--acelerar", type=float, default=30,
                            help="Minutos simulados por minuto real en modo vivo")
        parser.add_argument("--semilla", type=int, default=11)

    def handle(self, *args, **o):
        self.rnd = random.Random(o["semilla"])
        if o["reset"]:
            self._crear_demo(o["dias"], o["cambio"], o["semilla"])
        if o["vivo"]:
            self._vivo(o["intervalo"], o["acelerar"], o["semilla"])
        if not o["reset"] and not o["vivo"]:
            self.stdout.write("Nada que hacer. Usá --reset y/o --vivo.")

    # ------------------------------------------------------------------ demo
    @transaction.atomic
    def _crear_demo(self, dias, cambio, semilla):
        Sala.objects.filter(nombre__startswith="Sala demo").delete()
        Receta.objects.filter(nombre__endswith="DEMO-001").delete()
        Receta.objects.filter(nombre__startswith="Receta demo").delete()

        sala = Sala.objects.create(nombre="Sala demo", descripcion="Datos simulados para desarrollo",
                                   latitud=-34.6, longitud=-58.4)
        ahora = timezone.now().replace(second=0, microsecond=0)
        ahora -= timedelta(minutes=ahora.minute % PASO_MIN)
        inicio = ahora - timedelta(days=dias)
        # Receta del catálogo (tomate), igual que la elegiría un usuario
        ciclo = crear_ciclo_desde_catalogo(sala, "tomate", "DEMO-001", inicio, cerrar_anterior=False)
        # El productor pasó de plantín a crecimiento a los 12 días (decisión suya, no una fecha fija)
        if dias > 12:
            ciclo.cambiar_etapa(ciclo.receta.etapas.get(orden=2), momento=inicio + timedelta(days=12))
        momento_cambio = inicio + timedelta(days=cambio)
        PeriodoExperimento.objects.create(sala=sala, nombre="Antes: equipos a horario fijo",
                                          modo="horario", inicio=inicio, fin=momento_cambio)
        PeriodoExperimento.objects.create(sala=sala, nombre="Después: control automático por mediciones",
                                          modo="lazo_cerrado", inicio=momento_cambio)

        ext1 = Actuador.objects.create(sala=sala, nombre="Extractor 1", tipo="extractor", orden=1)
        ext2 = Actuador.objects.create(sala=sala, nombre="Extractor 2", tipo="extractor", orden=2)
        calef = Actuador.objects.create(sala=sala, nombre="Calefactor", tipo="calefactor")
        luces = Actuador.objects.create(sala=sala, nombre="Luces", tipo="luz")
        camara = Camara.objects.create(sala=sala, nombre="Cámara de demostración", tipo="foto", intervalo_seg=5,
                                       url=reverse("camara_demo", args=[sala.id]))
        # Una foto por día a las 12 h desde el inicio del ciclo, para que el time-lapse tenga material
        for d in range(dias + 1):
            momento = timezone.localtime(inicio + timedelta(days=d)).replace(hour=12, minute=0)
            if momento <= ahora:
                svg = svg_demo(sala.nombre, momento, crecimiento_del_ciclo(ciclo, momento))
                guardar_foto_diaria(camara, ciclo, momento, svg.encode(), "svg")

        modelo, clima, ctl = ModeloInvernadero(semilla=semilla), ClimaExterior(semilla=semilla), ControladorClima()
        estado = {ext1.id: False, ext2.id: False, calef.id: False, luces.id: False}
        lecturas, acciones = [], []
        fuera_desde, alerta_abierta = None, False
        problema_desde = None
        t, contador = inicio, 0

        self.stdout.write(f"Generando {dias} días de datos simulados…")
        ventanas = ciclo.ventanas_etapas()
        rangos = {e.id: {r.variable: (r.minimo, r.maximo) for r in e.rangos.all()} for e, _, _ in ventanas}

        def etapa_de(momento):
            for e, ini, fin in ventanas:
                if ini <= momento < fin:
                    return e
            return ventanas[-1][0]

        while t <= ahora:
            etapa = etapa_de(t)
            rv = Rango(*rangos[etapa.id]["vpd"])
            rt = Rango(*rangos[etapa.id]["temperatura"])
            luz = luces_encendidas(timezone.localtime(t), etapa.horas_luz)
            te, he = clima.en(timezone.localtime(t))
            lazo = t >= momento_cambio

            if lazo:
                ultimo = getattr(self, "_ultimo", None)
                if ultimo:
                    s = ctl.evaluar(ultimo["temperatura"], ultimo["humedad"], ultimo["vpd"], rv, rt, PASO_MIN, te, he)
                    deseado_ext = nivel_a_extractores(s.nivel_extraccion, 2)
                    deseado_cal = s.calefactor
                    motivo_ext, motivo_cal, origen = s.motivo_extraccion, s.motivo_calefactor, "automatico"
                else:
                    deseado_ext, deseado_cal, motivo_ext, motivo_cal, origen = [False, False], False, "", "", "automatico"
            else:
                minuto = timezone.localtime(t).minute
                deseado_ext = [minuto < 15, 30 <= minuto < 45]  # misma programación que extractores_por_horario
                deseado_cal = calefactor_por_horario(timezone.localtime(t))
                motivo_ext = motivo_cal = "programación horaria"
                origen = "horario"

            for act, valor, motivo, org in [
                (ext1, deseado_ext[0], motivo_ext, origen), (ext2, deseado_ext[1], motivo_ext, origen),
                (calef, deseado_cal, motivo_cal, origen), (luces, luz, "fotoperíodo", "horario"),
            ]:
                if estado[act.id] != valor:
                    estado[act.id] = valor
                    acciones.append(AccionActuador(actuador=act, momento=t, encendido=valor, origen=org, motivo=motivo))

            l = modelo.paso(PASO_MIN, int(estado[ext1.id]) + int(estado[ext2.id]), luz, te, he, estado[calef.id])
            self._ultimo = l
            for v in VARIABLES_GUARDADAS:
                lecturas.append(Lectura(sala=sala, variable=v, valor=round(l[v], 3), momento=t, origen="simulado"))

            # Alertas: VPD fuera de rango durante más de 60 minutos
            if not rv.contiene(l["vpd"]):
                fuera_desde = fuera_desde or t
                if not alerta_abierta and t - fuera_desde >= timedelta(minutes=60):
                    alerta_abierta = True
                    tipo = "bajo" if l["vpd"] < rv.minimo else "alto"
                    Alerta.objects.create(sala=sala, momento=t, nivel="advertencia", variable="vpd",
                                          resuelta=t < ahora - timedelta(hours=12),
                                          mensaje=f"VPD {tipo} durante más de 1 h ({l['vpd']:.2f} kPa; objetivo {rv.minimo}–{rv.maximo})")
            else:
                fuera_desde, alerta_abierta = None, False

            # Intervención manual del operador: si de día el VPD lleva más de 2 h fuera
            # de rango, el operador entra y prende o apaga un extractor a mano.
            hora_local = timezone.localtime(t).hour
            if not rv.contiene(l["vpd"]) and 9 <= hora_local <= 20:
                problema_desde = problema_desde or t
                if t - problema_desde >= timedelta(hours=2) and self.rnd.random() < 0.08:
                    encender = l["vpd"] < rv.minimo
                    acciones.append(AccionActuador(actuador=ext2, momento=t, encendido=encender, origen="manual",
                                                   motivo="intervención del operador (simulada)"))
                    problema_desde = None
            else:
                problema_desde = None

            # Riego y recambio de solución cada 3 días a las 9:00
            if (t - inicio).days % 3 == 0 and timezone.localtime(t).hour == 9 and timezone.localtime(t).minute == 0:
                ph_med, ec_med = round(modelo.ph, 2), round(modelo.ec, 2)
                EventoBitacora.objects.create(ciclo=ciclo, momento=t, tipo="solucion", ph=ph_med, ec=ec_med,
                                              volumen_litros=40,
                                              descripcion=f"Recambio de solución. Antes: pH {ph_med}, EC {ec_med}.")
                rango_ec = rangos[etapa.id]["ec"]
                modelo.recambio_solucion(ph=6.0, ec=round(sum(rango_ec) / 2, 2))

            contador += 1
            if len(lecturas) >= 20000:
                Lectura.objects.bulk_create(lecturas)
                lecturas = []
            t += timedelta(minutes=PASO_MIN)

        Lectura.objects.bulk_create(lecturas)
        AccionActuador.objects.bulk_create(acciones)
        EventoBitacora.objects.create(ciclo=ciclo, momento=inicio + timedelta(days=2, hours=11), tipo="calibracion",
                                      descripcion="Calibración de sondas de pH (4,0 y 7,0) y EC (1,413 mS/cm).")
        EventoBitacora.objects.create(ciclo=ciclo, momento=inicio + timedelta(days=12, hours=16), tipo="poda",
                                      descripcion="Poda de hojas bajas para mejorar la circulación de aire.")
        for act in (ext1, ext2, calef, luces):
            act.encendido = estado[act.id]
            act.save()

        User = get_user_model()
        if not User.objects.filter(username="demo").exists():
            User.objects.create_superuser("demo", "", "demo1234")
            self.stdout.write(self.style.WARNING("Usuario creado: demo / demo1234 (solo para desarrollo)"))
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {contador} pasos, {Lectura.objects.filter(sala=sala).count()} lecturas, "
            f"{len(acciones)} acciones de actuadores."))

    # ------------------------------------------------------------------ vivo
    def _vivo(self, intervalo, acelerar, semilla):
        sala = Sala.objects.filter(nombre__startswith="Sala demo").first() or Sala.objects.first()
        if not sala:
            self.stderr.write("No hay salas. Ejecutá primero: python manage.py simular --reset")
            return
        ciclo = sala.ciclo_activo()
        ultimas = {v: sala.lecturas.filter(variable=v).order_by("-momento").first()
                   for v in ["temperatura", "humedad", "co2", "ph", "ec"]}
        modelo = ModeloInvernadero(semilla=semilla + 1)
        if ultimas["temperatura"] and ultimas["humedad"]:
            modelo.temp = ultimas["temperatura"].valor
            modelo.ah = humedad_absoluta(modelo.temp, ultimas["humedad"].valor)
        for v in ("co2", "ph", "ec"):
            if ultimas[v]:
                setattr(modelo, v, ultimas[v].valor)
        clima, ctl = ClimaExterior(semilla=semilla), ControladorClima()
        minutos_sim = intervalo / 60 * acelerar
        ultimo = None

        self.stdout.write(self.style.SUCCESS(
            f"Simulación en vivo de '{sala}' cada {intervalo:g} s (Ctrl+C para detener)."))
        try:
            while True:
                t = timezone.now()
                local = timezone.localtime(t)
                # Se leen en cada vuelta: si el usuario agrega un equipo desde la web, se usa enseguida
                extractores = list(sala.actuadores.filter(activo=True, tipo="extractor").order_by("orden"))
                calef = sala.actuadores.filter(activo=True, tipo="calefactor").first()
                luces = sala.actuadores.filter(activo=True, tipo="luz").first()
                humid = sala.actuadores.filter(activo=True, tipo="humidificador").first()
                deshum = sala.actuadores.filter(activo=True, tipo="deshumidificador").first()
                ventiladores = list(sala.actuadores.filter(activo=True, tipo="ventilador"))
                etapa = ciclo.etapa_en(t) if ciclo else None
                rv = Rango(*etapa.rango("vpd")) if etapa else Rango(0.8, 1.2)
                rt = Rango(*etapa.rango("temperatura")) if etapa else Rango(20, 28)
                luz = luces_encendidas(local, etapa.horas_luz if etapa else 18)
                te, he = clima.en(local)
                sala.refresh_from_db(fields=["control_pausado"])
                periodo = sala.periodo_activo(t)
                lazo = periodo is None or periodo.modo == "lazo_cerrado"

                # Decisión automática
                if lazo and ultimo:
                    rh = etapa.rango("humedad") if etapa else None
                    s = ctl.evaluar(ultimo["temperatura"], ultimo["humedad"], ultimo["vpd"], rv, rt, minutos_sim, te, he,
                                    rango_hr=Rango(*rh) if rh else None,
                                    tiene_humidificador=bool(humid), tiene_deshumidificador=bool(deshum))
                    deseado = nivel_a_extractores(s.nivel_extraccion, len(extractores))
                    deseado_cal, motivo, origen = s.calefactor, s.motivo_extraccion, "automatico"
                    deseado_hum, deseado_desh, motivo_hum = s.humidificador, s.deshumidificador, s.motivo_humedad
                else:
                    n = extractores_por_horario(local)
                    deseado = nivel_a_extractores(n, len(extractores))
                    deseado_cal, motivo, origen = calefactor_por_horario(local), "programación horaria", "horario"
                    deseado_hum = deseado_desh = False
                    motivo_hum = "programación horaria"

                # Aplicar respetando los actuadores en modo manual
                for act, valor in list(zip(extractores, deseado)) + [(calef, deseado_cal), (luces, luz),
                                                                       (humid, deseado_hum), (deshum, deseado_desh)] \
                        + [(v, True) for v in ventiladores]:  # circulación de aire continua
                    if act is None:
                        continue
                    act.refresh_from_db()
                    act.revisar_vencimiento(t)
                    if act.modo == "auto" and act.encendido != valor and (not sala.control_pausado or act == luces):
                        act.encendido = valor
                        act.save(update_fields=["encendido", "actualizado"])
                        AccionActuador.objects.create(actuador=act, momento=t, encendido=valor,
                                                      origen="horario" if act == luces else origen,
                                                      motivo="fotoperíodo" if act == luces else
                                                      (motivo_hum if act in (humid, deshum) else motivo))

                n_ext = sum(1 for a in extractores if a.encendido)
                l = modelo.paso(minutos_sim, n_ext, luz, te, he, bool(calef and calef.encendido),
                                humidificador=bool(humid and humid.encendido),
                                deshumidificador=bool(deshum and deshum.encendido))
                ultimo = l
                Lectura.objects.bulk_create([
                    Lectura(sala=sala, variable=v, valor=round(l[v], 3), momento=t, origen="simulado")
                    for v in VARIABLES_GUARDADAS
                ])
                self.stdout.write(
                    f"{local:%H:%M:%S}  T {l['temperatura']:.1f} °C  HR {l['humedad']:.0f}%  "
                    f"VPD {l['vpd']:.2f} kPa  extractores {n_ext}  calefactor {'on' if calef and calef.encendido else 'off'}")
                for foto in sacar_fotos_diarias(t, sala)[0]:
                    self.stdout.write(self.style.SUCCESS(f"Foto diaria guardada: {foto}"))
                time.sleep(intervalo)
        except KeyboardInterrupt:
            self.stdout.write("Simulación detenida.")
