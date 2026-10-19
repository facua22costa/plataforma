"""Foto diaria de cada cámara y time-lapse del ciclo.

Una vez por día, a la hora elegida (12 h por defecto), el sistema le pide una
foto a cada cámara y la guarda asociada al ciclo en curso. Si a esa hora el
sistema estaba apagado, la saca apenas vuelve a correr ese mismo día.

Lo llaman el servicio de control, la simulación en vivo y el comando
`python manage.py fotos_diarias` (para programarlo aparte).
"""
import logging

from django.core.files.base import ContentFile
from django.utils import timezone

log = logging.getLogger(__name__)
REINTENTO_MIN = 15      # si una cámara no responde, se vuelve a probar recién a los 15 minutos
_ultimo_error = {}      # id de cámara -> momento del último intento fallido


def svg_demo(nombre_sala, momento, crecimiento=0.6):
    """Dibujo de la sala para la cámara de demostración.

    `crecimiento` va de 0 (plantín) a 1 (fin del ciclo): las plantas crecen,
    suman hojas y al final dan frutos, así el time-lapse de la demo se mueve.
    """
    c = max(0.0, min(1.0, crecimiento))
    de_dia = 6 <= momento.hour < 20
    fondo, piso, luz = ("#dfe9d6", "#8a6f4e", "#fff7c2") if de_dia else ("#1f2a22", "#3b3024", "#2b3a2e")
    alto = 30 + 150 * c          # altura del tallo en píxeles (fila de adelante)
    n_hojas = 2 + int(8 * c)
    plantas = []
    for fila, (y, escala, cantidad, paso, corrimiento) in enumerate([(300, 0.75, 7, 90, 0), (360, 1.0, 6, 105, 20)]):
        for i in range(cantidad):
            x = 60 + i * paso + corrimiento
            h = alto * escala * (0.92 + 0.08 * ((i * 7 + fila * 3) % 5) / 4)  # pequeñas diferencias entre plantas
            partes = [f'<rect x="{x - 18 * escala:.0f}" y="{y:.0f}" width="{36 * escala:.0f}" height="{26 * escala:.0f}" rx="3" fill="#3a3a3a"/>',
                      f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y - h:.0f}" stroke="#3d6b2f" stroke-width="{(2 + 2 * c) * escala:.1f}"/>']
            for k in range(n_hojas):
                lado = -1 if k % 2 else 1
                hy = y - h * (k + 1) / (n_hojas + 0.5)
                hx = x + lado * (10 + 6 * c) * escala
                tam = (8 + 10 * c) * escala
                partes.append(f'<ellipse cx="{hx:.0f}" cy="{hy:.0f}" rx="{tam:.0f}" ry="{tam / 2:.0f}" '
                              f'transform="rotate({lado * 28} {hx:.0f} {hy:.0f})" fill="#4f8a3c"/>')
            if c > 0.7:  # frutos al final del ciclo
                for k in range(int((c - 0.7) * 10) + 1):
                    fy = y - h * (0.35 + 0.12 * k)
                    partes.append(f'<circle cx="{x + (8 if k % 2 else -8) * escala:.0f}" cy="{fy:.0f}" r="{6 * escala:.0f}" fill="#d0453b"/>')
            plantas.append("".join(partes))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 400" width="640" height="400">
<rect width="640" height="400" fill="{fondo}"/>
<polygon points="0,140 320,40 640,140" fill="{luz}" opacity="0.6"/>
<rect x="0" y="330" width="640" height="70" fill="{piso}"/>
{''.join(plantas)}
<rect x="12" y="12" width="236" height="30" rx="6" fill="rgba(0,0,0,.55)"/>
<circle cx="28" cy="27" r="6" fill="#e5484d"/>
<text x="42" y="32" font-family="sans-serif" font-size="14" fill="#fff">{nombre_sala} · {momento:%d/%m %H:%M}</text>
<text x="628" y="390" text-anchor="end" font-family="sans-serif" font-size="12" fill="rgba(255,255,255,.8)">Imagen de demostración</text>
</svg>"""


def crecimiento_del_ciclo(ciclo, momento):
    """Qué tan avanzado está el ciclo (0 a 1), según la duración de referencia del plan."""
    total = sum(e.duracion_dias for e in ciclo.receta.etapas.all()) or 1
    return (momento - ciclo.fecha_inicio).total_seconds() / 86400 / total


def guardar_foto_diaria(camara, ciclo, momento, datos, extension):
    from .models import FotoDiaria
    local = timezone.localtime(momento)
    foto = FotoDiaria(ciclo=ciclo, camara=camara, fecha=local.date(), momento=momento)
    foto.archivo.save(f"{ciclo.id}-{camara.id if camara else 0}-{local:%Y%m%d}.{extension}",
                      ContentFile(datos), save=False)
    foto.save()
    return foto


def sacar_fotos_diarias(ahora=None, sala=None):
    """Saca las fotos del día que falten. Devuelve (sacadas, errores)."""
    from nucleo.camara import ErrorCamara, capturar
    from .models import Camara, FotoDiaria

    ahora = ahora or timezone.now()
    local = timezone.localtime(ahora)
    camaras = Camara.objects.filter(activa=True, foto_diaria=True, hora_foto__lte=local.hour).select_related("sala")
    if sala is not None:
        camaras = camaras.filter(sala=sala)
    sacadas, errores = [], []
    for cam in camaras:
        ciclo = cam.sala.ciclo_activo()
        if not ciclo or FotoDiaria.objects.filter(ciclo=ciclo, camara=cam, fecha=local.date()).exists():
            continue
        fallo = _ultimo_error.get(cam.id)
        if fallo and (ahora - fallo).total_seconds() < REINTENTO_MIN * 60:
            continue
        try:
            if cam.es_demo:
                svg = svg_demo(cam.sala.nombre, local, crecimiento_del_ciclo(ciclo, ahora))
                sacadas.append(guardar_foto_diaria(cam, ciclo, ahora, svg.encode(), "svg"))
            else:
                sacadas.append(guardar_foto_diaria(cam, ciclo, ahora, capturar(cam.url_foto or cam.url), "jpg"))
        except ErrorCamara as e:
            _ultimo_error[cam.id] = ahora
            log.warning("Foto diaria de %s: %s", cam, e)
            errores.append((cam, str(e)))
    return sacadas, errores
