"""Controlador de clima con estado: aplica las reglas en cada ciclo de control.

Guarda el nivel actual y cuánto tiempo lleva en él (para el anti-ciclado).
Lo usan tanto el servicio de control real como el simulador.
"""
from dataclasses import dataclass

from .reglas import (Rango, decidir_calefaccion, decidir_deshumidificacion, decidir_extraccion,
                     decidir_humidificacion)
from .vpd import humedad_absoluta


@dataclass
class Salida:
    nivel_extraccion: int
    calefactor: bool
    motivo_extraccion: str
    motivo_calefactor: str
    cambio: bool
    humidificador: bool = False
    deshumidificador: bool = False
    motivo_humedad: str = ""


class ControladorClima:
    def __init__(self, nivel_inicial: int = 0, calefactor_inicial: bool = False):
        self.nivel = nivel_inicial
        self.calefactor = calefactor_inicial
        self.minutos_en_nivel = 999.0
        self.humidificador = False
        self.deshumidificador = False

    def evaluar(self, temperatura: float, humedad: float, vpd: float,
                rango_vpd: Rango, rango_temp: Rango, minutos: float,
                temp_exterior: float | None = None,
                humedad_exterior: float | None = None,
                rango_hr: Rango | None = None,
                tiene_humidificador: bool = False,
                tiene_deshumidificador: bool = False) -> Salida:
        """Decide todos los equipos. Solo actúa sobre los que la sala tiene;
        lo que falta lo informa el módulo de diagnóstico como recomendación."""
        ah_int = humedad_absoluta(temperatura, humedad)
        ah_ext = None
        if temp_exterior is not None and humedad_exterior is not None:
            ah_ext = humedad_absoluta(temp_exterior, humedad_exterior)

        self.minutos_en_nivel += minutos
        dec_ext = decidir_extraccion(vpd, temperatura, rango_vpd, rango_temp,
                                     self.nivel, self.minutos_en_nivel, ah_int, ah_ext)
        dec_cal = decidir_calefaccion(vpd, temperatura, rango_vpd, rango_temp, self.calefactor)

        cambio = dec_ext.nivel != self.nivel or bool(dec_cal.nivel) != self.calefactor
        if dec_ext.nivel != self.nivel:
            self.nivel = dec_ext.nivel
            self.minutos_en_nivel = 0.0
        self.calefactor = bool(dec_cal.nivel)

        motivo_humedad = ""
        if tiene_humidificador:
            d = decidir_humidificacion(vpd, humedad, rango_vpd, rango_hr, self.humidificador)
            cambio = cambio or bool(d.nivel) != self.humidificador
            self.humidificador, motivo_humedad = bool(d.nivel), d.motivo
        if tiene_deshumidificador:
            d = decidir_deshumidificacion(vpd, humedad, rango_vpd, rango_hr, self.deshumidificador)
            cambio = cambio or bool(d.nivel) != self.deshumidificador
            self.deshumidificador = bool(d.nivel)
            motivo_humedad = motivo_humedad if self.humidificador else d.motivo
        return Salida(self.nivel, self.calefactor, dec_ext.motivo, dec_cal.motivo, cambio,
                      self.humidificador, self.deshumidificador, motivo_humedad)
