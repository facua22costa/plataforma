"""Cámaras del cultivo: obtener una foto de una cámara en red.

Tipos de fuente que soporta la plataforma:
- "video": video en vivo MJPEG (multipart/x-mixed-replace). Es lo que entregan
  la ESP32-CAM (http://IP:81/stream), un celular viejo con la app IP Webcam
  (http://IP:8080/video) y las cámaras IP con RTSP pasadas por go2rtc/MediaMTX.
- "foto": una imagen JPEG que se vuelve a pedir cada tantos segundos
  (ESP32-CAM: http://IP/capture; IP Webcam: http://IP:8080/shot.jpg).

El navegador muestra la cámara directamente; el servidor solo la consulta
cuando hay que guardar una foto en la bitácora.
"""
import urllib.request

INICIO_JPEG = b"\xff\xd8"
FIN_JPEG = b"\xff\xd9"
MAX_BYTES = 4 * 1024 * 1024  # límite de lectura: una foto nunca pesa más que esto


class ErrorCamara(Exception):
    pass


def extraer_cuadro(datos):
    """Devuelve el primer JPEG completo dentro de los bytes recibidos (o None).

    Sirve tanto para una foto suelta como para un flujo MJPEG, donde los
    cuadros vienen uno detrás de otro separados por encabezados multipart.
    """
    inicio = datos.find(INICIO_JPEG)
    if inicio < 0:
        return None
    fin = datos.find(FIN_JPEG, inicio + 2)
    if fin < 0:
        return None
    return datos[inicio:fin + 2]


def capturar(url, timeout=8, abrir=urllib.request.urlopen):
    """Pide la URL y devuelve los bytes de una foto JPEG.

    Lee de a bloques hasta encontrar un cuadro completo, así funciona también
    con flujos de video que no terminan nunca.
    """
    if not url.lower().startswith(("http://", "https://")):
        raise ErrorCamara("La dirección de la cámara tiene que empezar con http:// o https://")
    try:
        respuesta = abrir(url, timeout=timeout)
    except Exception as e:  # red caída, cámara apagada, dirección mal escrita
        raise ErrorCamara(f"No se pudo conectar con la cámara ({e})") from e
    datos = b""
    try:
        while len(datos) < MAX_BYTES:
            bloque = respuesta.read(64 * 1024)
            if not bloque:
                break
            datos += bloque
            cuadro = extraer_cuadro(datos)
            if cuadro:
                return cuadro
    finally:
        respuesta.close()
    raise ErrorCamara("La cámara respondió, pero no mandó una imagen JPEG")
