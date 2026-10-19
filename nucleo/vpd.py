"""Cálculos psicrométricos: presión de vapor, VPD y humedad absoluta.

Unidades: temperatura en °C, humedad relativa en %, presiones en kPa,
humedad absoluta en g/m³.
"""
import math


def presion_saturacion(temp_c: float) -> float:
    """Presión de vapor de saturación (kPa) según la ecuación de Tetens."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def vpd_aire(temp_c: float, hr: float) -> float:
    """Déficit de presión de vapor del aire (kPa)."""
    return presion_saturacion(temp_c) * (1 - hr / 100)


def vpd_hoja(temp_aire: float, hr: float, temp_hoja: float | None = None) -> float:
    """Déficit de presión de vapor entre la hoja y el aire (kPa).

    Si no hay medición de temperatura de hoja, se asume igual a la del aire
    (el resultado coincide con el VPD del aire).
    """
    if temp_hoja is None:
        temp_hoja = temp_aire
    return presion_saturacion(temp_hoja) - presion_saturacion(temp_aire) * hr / 100


def humedad_absoluta(temp_c: float, hr: float) -> float:
    """Humedad absoluta (g de agua por m³ de aire)."""
    presion_vapor_pa = presion_saturacion(temp_c) * 1000 * hr / 100
    return 2.1674 * presion_vapor_pa / (273.15 + temp_c)


def hr_desde_humedad_absoluta(temp_c: float, ah: float) -> float:
    """Humedad relativa (%) correspondiente a una humedad absoluta dada."""
    ah_saturacion = humedad_absoluta(temp_c, 100)
    return max(0.0, min(100.0, 100 * ah / ah_saturacion))
