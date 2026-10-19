"""Modelo de datos de la plataforma.

Dos tipos de información conviven en la misma base:
- Series temporales: Lectura (miles de filas por día). En producción, la tabla
  se convierte en hypertable de TimescaleDB.
- Datos relacionales: salas, recetas, ciclos, bitácora, actuadores, alertas.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

# variable: (etiqueta, unidad, decimales)
VARIABLES = {
    "temperatura": ("Temperatura", "°C", 1),
    "humedad": ("Humedad relativa", "%", 0),
    "vpd": ("VPD de hoja", "kPa", 2),
    "co2": ("CO₂", "ppm", 0),
    "temp_hoja": ("Temperatura de hoja", "°C", 1),
    "luz": ("Luz", "lux", 0),
    "ph": ("pH de solución", "", 2),
    "ec": ("EC de solución", "mS/cm", 2),
    "temp_solucion": ("Temp. de solución", "°C", 1),
    "temp_exterior": ("Temperatura exterior", "°C", 1),
    "humedad_exterior": ("Humedad exterior", "%", 0),
}
VARIABLE_CHOICES = [(k, v[0]) for k, v in VARIABLES.items()]


class Sala(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    latitud = models.FloatField(null=True, blank=True, help_text="Para consultar el clima exterior")
    longitud = models.FloatField(null=True, blank=True)
    control_pausado = models.BooleanField(default=False,
                                          help_text="Si está activo, el sistema no prende ni apaga nada solo")
    pausado_desde = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.nombre

    def ciclo_activo(self):
        return self.ciclos.filter(fecha_fin__isnull=True).order_by("-fecha_inicio").first()

    def periodo_activo(self, momento=None):
        momento = momento or timezone.now()
        return (
            self.periodos.filter(inicio__lte=momento)
            .filter(models.Q(fin__isnull=True) | models.Q(fin__gt=momento))
            .order_by("-inicio")
            .first()
        )


class Lectura(models.Model):
    ORIGENES = [("sensor", "Sensor"), ("simulado", "Simulado"), ("manual", "Manual")]

    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name="lecturas")
    variable = models.CharField(max_length=30, choices=VARIABLE_CHOICES)
    valor = models.FloatField()
    momento = models.DateTimeField(db_index=True)
    origen = models.CharField(max_length=10, choices=ORIGENES, default="sensor")

    class Meta:
        indexes = [models.Index(fields=["sala", "variable", "momento"])]
        ordering = ["-momento"]

    def __str__(self):
        return f"{self.variable}={self.valor:.2f} @ {self.momento:%d/%m %H:%M}"


class Receta(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    cultivo = models.CharField(max_length=30, blank=True, default="",
                               help_text="Clave del catálogo de origen, si la tiene")
    fuentes = models.TextField(blank=True, default="", help_text="Bibliografía de los valores")
    validada_por = models.CharField(max_length=150, blank=True, default="",
                                    help_text="Profesional que revisó la receta (ej.: Ing. Agr. Nombre Apellido, MP 1234)")

    def __str__(self):
        return self.nombre


class Etapa(models.Model):
    receta = models.ForeignKey(Receta, on_delete=models.CASCADE, related_name="etapas")
    nombre = models.CharField(max_length=60)
    orden = models.PositiveSmallIntegerField()
    duracion_dias = models.PositiveSmallIntegerField()
    horas_luz = models.PositiveSmallIntegerField(default=18)
    avisos = models.JSONField(default=dict, blank=True,
                              help_text="Avisos en lenguaje simple por variable para esta etapa")

    class Meta:
        ordering = ["receta", "orden"]

    def __str__(self):
        return f"{self.receta} · {self.nombre}"

    def rango(self, variable):
        r = self.rangos.filter(variable=variable).first()
        return (r.minimo, r.maximo) if r else None


class RangoObjetivo(models.Model):
    etapa = models.ForeignKey(Etapa, on_delete=models.CASCADE, related_name="rangos")
    variable = models.CharField(max_length=30, choices=VARIABLE_CHOICES)
    minimo = models.FloatField()
    maximo = models.FloatField()

    class Meta:
        unique_together = [("etapa", "variable")]

    def __str__(self):
        return f"{self.variable}: {self.minimo}–{self.maximo}"


class Ciclo(models.Model):
    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name="ciclos")
    codigo_lote = models.CharField(max_length=30, unique=True)
    cultivo = models.CharField(max_length=100)
    receta = models.ForeignKey(Receta, on_delete=models.PROTECT, related_name="ciclos")
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField(null=True, blank=True)
    FERTILIZACION = [("mineral", "Mineral (fertilizantes minerales, hidroponía o fertirriego)"),
                     ("organica", "Orgánica")]
    fertilizacion = models.CharField(max_length=10, choices=FERTILIZACION, default="mineral",
                                     help_text="En orgánico el sistema no controla pH ni EC de la solución")
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_inicio"]

    def __str__(self):
        return f"{self.codigo_lote} ({self.cultivo})"

    @property
    def activo(self):
        return self.fecha_fin is None

    def dia(self, momento=None):
        momento = momento or timezone.now()
        return (momento - self.fecha_inicio).days + 1

    def ventanas_etapas(self):
        """Lista de (etapa, inicio, fin) de las etapas por las que pasó el ciclo.

        Las etapas las cambia el productor (no hay fechas fijas): cada cambio queda
        registrado en TransicionEtapa. La etapa actual se extiende hasta el fin del ciclo.
        Si el ciclo no tiene cambios registrados (datos viejos), se estiman con la
        duración de cada etapa de la receta.
        """
        transiciones = list(self.transiciones.select_related("etapa").order_by("inicio"))
        limite = self.fecha_fin or timezone.now() + timedelta(days=3650)
        if transiciones:
            ventanas = []
            for i, t in enumerate(transiciones):
                fin = transiciones[i + 1].inicio if i + 1 < len(transiciones) else limite
                ventanas.append((t.etapa, t.inicio, fin))
            return ventanas
        ventanas, inicio = [], self.fecha_inicio
        etapas = list(self.receta.etapas.all())
        for i, etapa in enumerate(etapas):
            fin = inicio + timedelta(days=etapa.duracion_dias)
            if i == len(etapas) - 1:
                fin = max(fin, limite)
            ventanas.append((etapa, inicio, fin))
            inicio = fin
        return ventanas

    def etapa_en(self, momento=None):
        momento = momento or timezone.now()
        for etapa, inicio, fin in self.ventanas_etapas():
            if inicio <= momento < fin:
                return etapa
        return None

    def inicio_etapa_actual(self):
        ahora = timezone.now()
        for etapa, inicio, fin in self.ventanas_etapas():
            if inicio <= ahora < fin:
                return inicio
        return None

    def etapa_siguiente(self):
        actual = self.etapa_en()
        if not actual:
            return None
        return self.receta.etapas.filter(orden__gt=actual.orden).order_by("orden").first()

    def cambiar_etapa(self, etapa, momento=None, usuario=None):
        """Registra que el cultivo pasó a `etapa` (decisión del productor)."""
        return TransicionEtapa.objects.create(ciclo=self, etapa=etapa, inicio=momento or timezone.now(),
                                              usuario=usuario)


class TransicionEtapa(models.Model):
    """Momento en que el productor pasó el cultivo a una etapa."""
    ciclo = models.ForeignKey(Ciclo, on_delete=models.CASCADE, related_name="transiciones")
    etapa = models.ForeignKey(Etapa, on_delete=models.CASCADE, related_name="+")
    inicio = models.DateTimeField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["inicio"]
        verbose_name = "cambio de etapa"
        verbose_name_plural = "cambios de etapa"


class PeriodoExperimento(models.Model):
    """Período de la validación experimental: control por horario vs. lazo cerrado."""
    MODOS = [("horario", "Equipos a horario fijo"), ("lazo_cerrado", "Control automático por mediciones")]

    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name="periodos")
    nombre = models.CharField(max_length=100)
    modo = models.CharField(max_length=20, choices=MODOS)
    inicio = models.DateTimeField()
    fin = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["inicio"]

    def __str__(self):
        return self.nombre


class Actuador(models.Model):
    TIPOS = [
        ("extractor", "Extractor"), ("calefactor", "Calefactor"), ("luz", "Luces"),
        ("humidificador", "Humidificador"), ("deshumidificador", "Deshumidificador"),
        ("ventilador", "Ventilador interno"),
        ("riego", "Riego"), ("otro", "Otro"),
    ]
    DRIVERS = [("simulado", "Simulado"), ("tuya", "Tuya / Smart Life"), ("shelly", "Shelly")]
    MODOS = [("auto", "Automático"), ("manual", "Manual")]

    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name="actuadores")
    nombre = models.CharField(max_length=60)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    driver = models.CharField(max_length=20, choices=DRIVERS, default="simulado")
    config = models.JSONField(default=dict, blank=True, help_text="Datos de conexión del driver")
    orden = models.PositiveSmallIntegerField(default=1, help_text="Orden de encendido escalonado")
    encendido = models.BooleanField(default=False)
    modo = models.CharField(max_length=10, choices=MODOS, default="auto")
    activo = models.BooleanField(default=True, help_text="Desmarcar si el equipo ya no está en la sala (se conserva su historial)")
    manual_hasta = models.DateTimeField(null=True, blank=True,
                                        help_text="Si está en manual, cuándo vuelve solo a automático")
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sala", "tipo", "orden"]
        verbose_name_plural = "actuadores"

    def __str__(self):
        return self.nombre

    def revisar_vencimiento(self, momento=None):
        """Si el modo manual tenía fecha de vencimiento y ya pasó, vuelve a automático."""
        momento = momento or timezone.now()
        if self.modo == "manual" and self.manual_hasta and momento >= self.manual_hasta:
            self.modo, self.manual_hasta = "auto", None
            self.save(update_fields=["modo", "manual_hasta", "actualizado"])
            return True
        return False


class AccionActuador(models.Model):
    ORIGENES = [("automatico", "Automático"), ("manual", "Manual"), ("horario", "Horario")]

    actuador = models.ForeignKey(Actuador, on_delete=models.CASCADE, related_name="acciones")
    momento = models.DateTimeField(db_index=True)
    encendido = models.BooleanField()
    origen = models.CharField(max_length=12, choices=ORIGENES)
    motivo = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-momento"]
        verbose_name_plural = "acciones de actuadores"


class Alerta(models.Model):
    NIVELES = [("info", "Información"), ("advertencia", "Advertencia"), ("critica", "Crítica")]

    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name="alertas")
    momento = models.DateTimeField(db_index=True)
    nivel = models.CharField(max_length=12, choices=NIVELES, default="advertencia")
    variable = models.CharField(max_length=30, choices=VARIABLE_CHOICES, blank=True)
    mensaje = models.CharField(max_length=250)
    resuelta = models.BooleanField(default=False)

    class Meta:
        ordering = ["-momento"]


class EventoBitacora(models.Model):
    TIPOS = [
        ("riego", "Riego"), ("solucion", "Preparación / recambio de solución"),
        ("medicion", "Medición manual"), ("calibracion", "Calibración de sonda"),
        ("poda", "Poda / manejo"), ("plaga", "Plaga o enfermedad"),
        ("aplicacion", "Aplicación de producto"), ("foto", "Foto del cultivo"), ("otro", "Otro"),
    ]

    ciclo = models.ForeignKey(Ciclo, on_delete=models.CASCADE, related_name="eventos")
    momento = models.DateTimeField(default=timezone.now)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    descripcion = models.TextField(blank=True)
    ph = models.FloatField(null=True, blank=True, verbose_name="pH")
    ec = models.FloatField(null=True, blank=True, verbose_name="EC (mS/cm)")
    volumen_litros = models.FloatField(null=True, blank=True)
    foto = models.FileField(upload_to="bitacora/%Y/%m/", blank=True, default="", verbose_name="Foto (opcional)")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-momento"]
        verbose_name = "evento de bitácora"
        verbose_name_plural = "bitácora"


class Camara(models.Model):
    """Cámara apuntando al cultivo. El navegador la muestra directo; el servidor
    solo la consulta para guardar fotos en la bitácora (ver nucleo/camara.py)."""
    TIPOS = [("video", "Video en vivo (MJPEG)"), ("foto", "Foto que se actualiza sola")]

    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name="camaras")
    nombre = models.CharField(max_length=60, default="Cámara")
    tipo = models.CharField(max_length=10, choices=TIPOS, default="video")
    url = models.CharField(max_length=300, verbose_name="Dirección de la cámara",
                           help_text="Ej.: http://192.168.0.50:81/stream (ESP32-CAM) o http://192.168.0.60:8080/video (celular)")
    url_foto = models.CharField(max_length=300, blank=True, verbose_name="Dirección para sacar fotos (opcional)",
                                help_text="Ej.: http://192.168.0.50/capture. Si está vacía, se toma un cuadro del video.")
    intervalo_seg = models.PositiveSmallIntegerField(default=10, help_text="Cada cuánto se actualiza si es tipo foto")
    foto_diaria = models.BooleanField(default=True, verbose_name="Sacar una foto por día (para el time-lapse)")
    hora_foto = models.PositiveSmallIntegerField(default=12, verbose_name="Hora de la foto diaria",
                                                 help_text="De 0 a 23. Conviene una hora con las luces prendidas.")
    activa = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["sala", "orden", "id"]
        verbose_name = "cámara"
        verbose_name_plural = "cámaras"

    def __str__(self):
        return f"{self.nombre} ({self.sala})"

    @property
    def es_demo(self):
        return self.url.startswith("/")


class FotoDiaria(models.Model):
    """Una foto por día y por cámara: con todas juntas se arma el time-lapse del ciclo."""
    ciclo = models.ForeignKey(Ciclo, on_delete=models.CASCADE, related_name="fotos_diarias")
    camara = models.ForeignKey(Camara, null=True, blank=True, on_delete=models.SET_NULL, related_name="fotos_diarias")
    fecha = models.DateField()
    momento = models.DateTimeField(default=timezone.now)
    archivo = models.FileField(upload_to="timelapse/%Y/%m/")

    class Meta:
        ordering = ["ciclo", "fecha"]
        verbose_name = "foto diaria"
        verbose_name_plural = "fotos diarias (time-lapse)"
        constraints = [models.UniqueConstraint(fields=["ciclo", "camara", "fecha"], name="una_foto_por_dia_y_camara")]

    def __str__(self):
        return f"{self.ciclo} · {self.fecha:%d/%m/%Y}"


class Cosecha(models.Model):
    ciclo = models.ForeignKey(Ciclo, on_delete=models.CASCADE, related_name="cosechas")
    fecha = models.DateField()
    UNIDADES = [("kg", "kilos"), ("g", "gramos")]
    # Los nombres de los campos se mantienen por compatibilidad; el valor está en la unidad elegida.
    peso_humedo_g = models.FloatField(verbose_name="Cantidad cosechada (peso fresco)")
    peso_seco_g = models.FloatField(null=True, blank=True, verbose_name="Peso seco (opcional)")
    unidad = models.CharField(max_length=2, choices=UNIDADES, default="kg")
    calidad = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1 a 5")
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha"]
