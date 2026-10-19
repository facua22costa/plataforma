"""Capa de abstracción de actuadores, agnóstica de marca.

La lógica de control solo conoce la interfaz DriverActuador. Cada fabricante
tiene su propio driver. Para sumar una marca nueva se escribe una clase más y
se registra en DRIVERS, sin tocar el resto del sistema.
"""
from abc import ABC, abstractmethod
import json
import urllib.request


class ErrorDriver(Exception):
    """El dispositivo no respondió o rechazó el comando."""


class DriverActuador(ABC):
    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def encender(self) -> None: ...

    @abstractmethod
    def apagar(self) -> None: ...

    @abstractmethod
    def estado(self) -> bool: ...

    def aplicar(self, encendido: bool) -> None:
        self.encender() if encendido else self.apagar()


class DriverSimulado(DriverActuador):
    """Actuador en memoria, para el simulador y las pruebas."""

    def __init__(self, config=None):
        super().__init__(config)
        self._encendido = bool(self.config.get("estado_inicial", False))

    def encender(self):
        self._encendido = True

    def apagar(self):
        self._encendido = False

    def estado(self):
        return self._encendido


class DriverTuya(DriverActuador):
    """Interruptores Tuya / Smart Life, controlados por la red local.

    config: {"device_id": ..., "ip": ..., "local_key": ..., "version": 3.3}
    La local_key se obtiene una sola vez desde la plataforma de desarrolladores
    de Tuya, vinculando la cuenta de Smart Life.
    """

    def _dispositivo(self):
        try:
            import tinytuya
        except ImportError as exc:
            raise ErrorDriver("Falta instalar tinytuya: pip install tinytuya") from exc
        d = tinytuya.OutletDevice(
            self.config["device_id"], self.config["ip"], self.config["local_key"]
        )
        d.set_version(float(self.config.get("version", 3.3)))
        return d

    def encender(self):
        respuesta = self._dispositivo().turn_on()
        if isinstance(respuesta, dict) and "Error" in respuesta:
            raise ErrorDriver(respuesta["Error"])

    def apagar(self):
        respuesta = self._dispositivo().turn_off()
        if isinstance(respuesta, dict) and "Error" in respuesta:
            raise ErrorDriver(respuesta["Error"])

    def estado(self):
        datos = self._dispositivo().status()
        if "Error" in datos:
            raise ErrorDriver(datos["Error"])
        return bool(datos.get("dps", {}).get(str(self.config.get("dp", 1))))


class DriverShelly(DriverActuador):
    """Relés Shelly (API HTTP local, generación 1). config: {"ip": ..., "canal": 0}"""

    def _llamar(self, accion: str | None = None) -> dict:
        canal = self.config.get("canal", 0)
        url = f"http://{self.config['ip']}/relay/{canal}"
        if accion:
            url += f"?turn={accion}"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return json.loads(r.read())
        except OSError as exc:
            raise ErrorDriver(f"Shelly sin respuesta: {exc}") from exc

    def encender(self):
        self._llamar("on")

    def apagar(self):
        self._llamar("off")

    def estado(self):
        return bool(self._llamar().get("ison"))


DRIVERS: dict[str, type[DriverActuador]] = {
    "simulado": DriverSimulado,
    "tuya": DriverTuya,
    "shelly": DriverShelly,
}


def crear_driver(tipo: str, config: dict | None = None) -> DriverActuador:
    try:
        return DRIVERS[tipo](config)
    except KeyError as exc:
        raise ErrorDriver(f"Driver desconocido: {tipo}") from exc
