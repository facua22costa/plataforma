"""Modelo simplificado de un invernadero, para desarrollo y demostración.

No pretende ser un modelo agronómico exacto: reproduce el comportamiento
cualitativo (las luces calientan, las plantas transpiran, la extracción
intercambia aire con el exterior) para poder probar el dashboard y la lógica
de control antes de tener el hardware instalado.

Los datos que genera son SIMULADOS y deben presentarse como tales.
"""
from dataclasses import dataclass, field
from datetime import datetime
import math
import random

from .vpd import humedad_absoluta, hr_desde_humedad_absoluta, vpd_hoja


@dataclass
class ClimaExterior:
    """Clima exterior sintético: ciclo diario con variación entre días."""
    temp_media: float = 17.0
    amplitud: float = 5.0
    hr_media: float = 72.0
    semilla: int = 7
    _variacion_dia: dict = field(default_factory=dict)

    def _dia(self, momento: datetime) -> tuple[float, float]:
        clave = momento.date().toordinal()
        if clave not in self._variacion_dia:
            rnd = random.Random(self.semilla * 100003 + clave)
            self._variacion_dia[clave] = (rnd.uniform(-3, 3), rnd.uniform(-10, 12))
        return self._variacion_dia[clave]

    def en(self, momento: datetime) -> tuple[float, float]:
        hora = momento.hour + momento.minute / 60
        delta_t, delta_hr = self._dia(momento)
        fase = math.sin(2 * math.pi * (hora - 9) / 24)
        temp = self.temp_media + delta_t + self.amplitud * fase
        hr = self.hr_media + delta_hr - 14 * fase
        return temp, max(30.0, min(98.0, hr))


@dataclass
class ModeloInvernadero:
    temp: float = 22.0
    ah: float = 12.0              # humedad absoluta interior (g/m³)
    co2: float = 450.0
    ph: float = 6.0
    ec: float = 1.4
    renovacion_base: float = 0.4  # renovaciones de aire por hora sin extractores
    renovacion_extractor: float = 1.5
    calor_luces: float = 0.40     # °C por paso de 5 min con luces encendidas
    calor_noche: float = 0.25
    perdida: float = 0.003        # pérdida por envolvente, fracción por paso
    transpiracion_dia: float = 0.40
    transpiracion_noche: float = 0.10
    calor_calefactor: float = 0.70
    semilla: int = 11

    def __post_init__(self):
        self._rnd = random.Random(self.semilla)

    def paso(self, minutos: float, extractores: int, luces: bool,
             temp_ext: float, hr_ext: float, calefactor: bool = False,
             humidificador: bool = False, deshumidificador: bool = False) -> dict:
        """Avanza el modelo y devuelve las lecturas de los sensores."""
        escala = minutos / 5
        ach = self.renovacion_base + self.renovacion_extractor * extractores
        f = 1 - math.exp(-ach * minutos / 60)

        calor = (self.calor_luces if luces else self.calor_noche) * escala
        if calefactor:
            calor += self.calor_calefactor * escala
        self.temp += f * (temp_ext - self.temp) + self.perdida * escala * (temp_ext - self.temp) + calor
        self.temp += self._rnd.gauss(0, 0.05)

        ah_ext = humedad_absoluta(temp_ext, hr_ext)
        transp = (self.transpiracion_dia if luces else self.transpiracion_noche) * escala
        self.ah += f * (ah_ext - self.ah) + transp
        if humidificador:
            self.ah += 0.35 * escala
        if deshumidificador:
            self.ah -= 0.30 * escala
            self.temp += 0.05 * escala  # el deshumidificador libera algo de calor
        # Condensación: el aire no puede superar la saturación
        self.ah = min(self.ah, humedad_absoluta(self.temp, 97))

        consumo = 9.0 if luces else -2.0  # fotosíntesis de día, respiración de noche
        self.co2 += f * (420 - self.co2) - consumo * escala + self._rnd.gauss(0, 3)
        self.co2 = max(250.0, self.co2)

        self.ph += 0.0006 * escala + self._rnd.gauss(0, 0.004)
        self.ec += 0.0004 * escala + self._rnd.gauss(0, 0.003)

        hr = hr_desde_humedad_absoluta(self.temp, self.ah) + self._rnd.gauss(0, 0.4)
        temp_hoja = self.temp - (1.2 if luces else 0.4) + self._rnd.gauss(0, 0.1)
        lecturas = {
            "temperatura": self.temp,
            "humedad": hr,
            "temp_hoja": temp_hoja,
            "co2": self.co2,
            "luz": (42000 + self._rnd.gauss(0, 800)) if luces else max(0.0, self._rnd.gauss(2, 1)),
            "ph": self.ph,
            "ec": self.ec,
            "temp_solucion": 19 + 0.3 * (self.temp - 20) + self._rnd.gauss(0, 0.05),
            "temp_exterior": temp_ext,
            "humedad_exterior": hr_ext,
        }
        lecturas["vpd"] = vpd_hoja(self.temp, hr, temp_hoja)
        return lecturas

    def recambio_solucion(self, ph: float = 6.0, ec: float = 1.4) -> None:
        """Simula un recambio o corrección de la solución nutritiva."""
        self.ph, self.ec = ph, ec


def extractores_por_horario(momento: datetime) -> int:
    """Programación horaria típica (situación actual del productor):
    extractor 1 los primeros 15 minutos de cada hora, extractor 2 de :30 a :45."""
    m = momento.minute
    return int(m < 15) + int(30 <= m < 45)


def calefactor_por_horario(momento: datetime) -> bool:
    """Programación horaria típica del calefactor: de 22:00 a 8:00."""
    return momento.hour >= 22 or momento.hour < 8


def luces_encendidas(momento: datetime, horas_luz: int) -> bool:
    """Fotoperíodo que arranca a las 6:00."""
    return (momento.hour - 6) % 24 < horas_luz
