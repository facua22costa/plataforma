"""Motor de reglas de control de clima.

Decide el nivel de extracción (0 = apagado, 1 = un extractor, 2 = ambos)
a partir del VPD, la temperatura y el clima exterior. Es una función pura:
recibe el estado y devuelve una decisión, sin tocar hardware ni base de datos.
Así la misma lógica corre en el servicio real y en el simulador.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rango:
    minimo: float
    maximo: float

    @property
    def centro(self) -> float:
        return (self.minimo + self.maximo) / 2

    def contiene(self, valor: float) -> bool:
        return self.minimo <= valor <= self.maximo


@dataclass(frozen=True)
class Decision:
    nivel: int
    motivo: str


# Parámetros de la estrategia (configurables en el futuro desde la receta)
MARGEN_MUY_HUMEDO = 0.15      # kPa por debajo del mínimo de VPD para usar ambos extractores
MARGEN_MUY_CALIENTE = 2.0     # °C por encima del máximo para usar ambos extractores
MINUTOS_MINIMOS_EN_NIVEL = 5  # anti-ciclado: protege los motores
DIFERENCIA_AH_UTIL = 0.5      # g/m³: extraer solo sirve si afuera hay menos humedad absoluta


def decidir_extraccion(
    vpd: float,
    temperatura: float,
    rango_vpd: Rango,
    rango_temp: Rango,
    nivel_actual: int,
    minutos_en_nivel: float,
    ah_interior: float | None = None,
    ah_exterior: float | None = None,
) -> Decision:
    """Calcula el nivel de extracción deseado.

    Estrategia:
    - Escalonada: un extractor ante un desvío leve, ambos ante uno fuerte.
    - Histéresis: una vez encendida, la extracción sigue hasta que el VPD
      llega al centro del rango (no apenas vuelve a entrar).
    - Anti-ciclado: no cambia de nivel antes de MINUTOS_MINIMOS_EN_NIVEL,
      salvo emergencia térmica.
    - Clima exterior: si el aire de afuera no está más seco que el de adentro,
      extraer no baja la humedad y no se extrae por humedad.
    """
    muy_caliente = temperatura > rango_temp.maximo + MARGEN_MUY_CALIENTE
    caliente = temperatura > rango_temp.maximo

    if minutos_en_nivel < MINUTOS_MINIMOS_EN_NIVEL and not muy_caliente:
        return Decision(nivel_actual, "espera el tiempo mínimo para no forzar los motores")

    extraer_seca = True
    if ah_interior is not None and ah_exterior is not None:
        extraer_seca = ah_exterior < ah_interior - DIFERENCIA_AH_UTIL

    humedo = vpd < rango_vpd.minimo
    muy_humedo = vpd < rango_vpd.minimo - MARGEN_MUY_HUMEDO

    if muy_caliente:
        return Decision(2, f"hace mucho calor ({temperatura:.1f} °C)")
    # Prioridad de la temperatura: con el ambiente frío, extraer enfría más
    # y empeora el VPD de hoja, aunque la humedad relativa sea alta.
    if temperatura < rango_temp.minimo:
        return Decision(0, f"hace frío ({temperatura:.1f} °C): no ventila para no enfriar más")
    if muy_humedo and extraer_seca:
        return Decision(2, f"aire muy húmedo (VPD {vpd:.2f} kPa)")
    if caliente:
        return Decision(max(1, min(nivel_actual, 2)), f"hace calor ({temperatura:.1f} °C)")
    if humedo and extraer_seca:
        return Decision(max(1, nivel_actual), f"aire húmedo (VPD {vpd:.2f} kPa)")
    if humedo and not extraer_seca:
        return Decision(0, "aire húmedo, pero afuera está igual o más húmedo: ventilar no ayuda")

    # Histéresis: mantener la extracción hasta llegar al centro del rango
    if nivel_actual > 0 and vpd < rango_vpd.centro and extraer_seca:
        return Decision(nivel_actual, "sigue ventilando hasta llegar al punto ideal")

    return Decision(0, "ambiente en rango")


def decidir_calefaccion(
    vpd: float,
    temperatura: float,
    rango_vpd: Rango,
    rango_temp: Rango,
    encendido: bool,
) -> Decision:
    """Decide el calefactor.

    Además de corregir el frío, aplica la estrategia clásica de "calentar y
    ventilar": con el aire muy húmedo, subir la temperatura aumenta la
    capacidad del aire de retener agua y sube el VPD, mientras la extracción
    saca la humedad.
    """
    if temperatura >= rango_temp.maximo - 1:
        return Decision(0, "la temperatura está cerca del máximo")
    if temperatura < rango_temp.minimo + 1:
        return Decision(1, f"hace frío ({temperatura:.1f} °C)")
    if vpd < rango_vpd.minimo and temperatura < rango_temp.centro:
        return Decision(1, "calienta para secar el aire")
    if encendido and temperatura < rango_temp.minimo + 3:
        return Decision(1, "sigue calentando hasta llegar al punto ideal")
    return Decision(0, "ambiente en rango")


def decidir_humidificacion(vpd: float, humedad: float, rango_vpd: Rango,
                           rango_hr: Rango | None, encendido: bool) -> Decision:
    """Humidificador: corrige el aire seco (VPD alto), que con solo extractores no se puede corregir."""
    if (rango_hr and humedad > rango_hr.maximo) or vpd < rango_vpd.minimo:
        return Decision(0, "el aire ya está húmedo")
    if vpd > rango_vpd.maximo or (rango_hr and humedad < rango_hr.minimo):
        return Decision(1, f"aire seco (VPD {vpd:.2f} kPa)")
    if encendido and vpd > rango_vpd.centro:
        return Decision(1, "sigue humidificando hasta llegar al punto ideal")
    return Decision(0, "ambiente en rango")


def decidir_deshumidificacion(vpd: float, humedad: float, rango_vpd: Rango,
                              rango_hr: Rango | None, encendido: bool) -> Decision:
    """Deshumidificador: saca humedad sin cambiar aire con el exterior (útil con frío o lluvia)."""
    if vpd > rango_vpd.maximo or (rango_hr and humedad < rango_hr.minimo):
        return Decision(0, "el aire ya está seco")
    if vpd < rango_vpd.minimo or (rango_hr and humedad > rango_hr.maximo):
        return Decision(1, f"aire húmedo (VPD {vpd:.2f} kPa)")
    if encendido and vpd < rango_vpd.centro:
        return Decision(1, "sigue secando hasta llegar al punto ideal")
    return Decision(0, "ambiente en rango")


def nivel_a_extractores(nivel: int, cantidad: int) -> list[bool]:
    """Convierte un nivel en el estado de cada extractor (escalonado)."""
    return [i < nivel for i in range(cantidad)]
