"""Catálogo de recetas predeterminadas por cultivo.

Cada receta define etapas con una duración de referencia, horas de luz, rangos
objetivo y avisos en lenguaje simple. La duración es solo orientativa: el cambio
de etapa lo decide el productor desde el panel. Los valores salen de las fuentes citadas en FUENTES
(ver el borrador de tesis). El VPD se calculó con la ecuación de Tetens a la
temperatura media del rango, entre la humedad máxima y la mínima.

El usuario puede editar cualquier valor después de crear el ciclo, o cargar su
propia receta desde la administración.
"""

FUENTES = {
    1: "Sosa, M. (2020). Pautas de manejo para tomate en invernadero. INTA EEA El Colorado.",
    2: "Contardi, C. A. (2023). Manual de Hidroponia. INTA EEA Mendoza.",
    3: "Castañares, J. L. (2022). Hidroponia para hortalizas de hoja. Fundamentos. INTA EEA AMBA.",
    4: "Birgi, J. A. y Gargaglione, V. (2021). Frutilla en hidroponía en Santa Cruz. INTA EEA Santa Cruz.",
    5: "Iglesias, N. B. (2015). Tomate en invernadero. INTA EEA Alto Valle.",
    6: "Infoagro. El cultivo del tomate.",
    7: "Infoagro. El cultivo del pimiento.",
    8: "Infoagro. El cultivo de la lechuga.",
    9: "Pacheco, R. M. et al. (2023). El cultivo de la frutilla en Corrientes. INTA EEA Bella Vista.",
    10: "SIAP, Gobierno de México (2023). Albahaca, monografía.",
    11: "Portal Frutícola (2026). El top 10 de los cultivos que conviene tener en invernaderos.",
}

_CO2 = (400, 1200)  # referencia general, sin fuente específica por cultivo

CATALOGO = {
    "tomate": {
        "nombre": "Tomate",
        "descripcion": "Lo más delicado es la floración: con humedad o temperatura fuera de rango no cuajan los frutos. También vigila las noches frías, que frenan el crecimiento.",
        "sistema": "Invernadero · suelo o sustrato",
        "fuentes": [1, 2, 3, 5, 6],
        "etapas": [
            {"nombre": "Plantín", "dias": 30, "luz": 14,
             "rangos": {"temperatura": (15, 25), "humedad": (60, 80), "vpd": (0.5, 0.9), "co2": _CO2,
                        "ph": (5.5, 6.5), "ec": (2.0, 2.5)},
             "avisos": {"temperatura": "Por debajo de 13 °C la planta detiene el crecimiento."}},
            {"nombre": "Crecimiento", "dias": 30, "luz": 14,
             "rangos": {"temperatura": (15, 25), "humedad": (60, 80), "vpd": (0.5, 0.9), "co2": _CO2,
                        "ph": (5.5, 6.5), "ec": (2.0, 2.5)},
             "avisos": {"temperatura": "Por debajo de 13 °C la planta detiene el crecimiento."}},
            {"nombre": "Floración y fruto", "dias": 90, "luz": 14,
             "rangos": {"temperatura": (15, 25), "humedad": (60, 80), "vpd": (0.5, 0.9), "co2": _CO2,
                        "ph": (5.5, 6.5), "ec": (2.0, 2.5)},
             "avisos": {
                 "humedad": "En floración, con humedad alta se dificulta la fecundación y aparecen hongos; con humedad baja el polen no se fija.",
                 "temperatura": "Por encima de 25 °C o por debajo de 12 °C la fecundación falla."}},
        ],
    },
    "pimiento": {
        "nombre": "Pimiento / morrón",
        "descripcion": "En floración necesita al menos 18 °C, más que el tomate. El sistema vigila sobre todo las noches frías.",
        "sistema": "Invernadero · sustrato",
        "fuentes": [2, 7],
        "etapas": [
            {"nombre": "Plantín", "dias": 40, "luz": 14,
             "rangos": {"temperatura": (16, 25), "humedad": (50, 70), "vpd": (0.7, 1.2), "co2": _CO2,
                        "ph": (5.5, 6.5), "ec": (1.8, 2.8)},
             "avisos": {"temperatura": "Por debajo de 15 °C el crecimiento se frena."}},
            {"nombre": "Crecimiento", "dias": 30, "luz": 14,
             "rangos": {"temperatura": (16, 25), "humedad": (50, 70), "vpd": (0.7, 1.2), "co2": _CO2,
                        "ph": (5.5, 6.5), "ec": (1.8, 2.8)},
             "avisos": {"temperatura": "Por debajo de 15 °C el crecimiento se frena."}},
            {"nombre": "Floración y fruto", "dias": 100, "luz": 14,
             "rangos": {"temperatura": (18, 28), "humedad": (50, 70), "vpd": (0.8, 1.4), "co2": _CO2,
                        "ph": (5.5, 6.5), "ec": (1.8, 2.8)},
             "avisos": {"temperatura": "En floración el mínimo es 18 °C; por debajo se resiente el cuaje."}},
        ],
    },
    "frutilla": {
        "nombre": "Frutilla",
        "descripcion": "Lo más delicado son las heladas durante la floración y, en hidroponía, la conductividad de la solución.",
        "sistema": "Macrotúnel o hidroponía NFT",
        "fuentes": [2, 3, 4, 9, 11],
        "etapas": [
            {"nombre": "Implantación", "dias": 30, "luz": 12,
             "rangos": {"temperatura": (15, 24), "humedad": (60, 75), "vpd": (0.6, 0.9), "co2": _CO2,
                        "ph": (5.5, 6.5), "ec": (1.0, 1.4)},
             "avisos": {"temperatura": "Entre 2 y 5 °C se detiene el crecimiento."}},
            {"nombre": "Floración y cosecha", "dias": 150, "luz": 11,
             "rangos": {"temperatura": (15, 24), "humedad": (60, 75), "vpd": (0.6, 0.9), "co2": _CO2,
                        "ph": (5.5, 6.5), "ec": (1.0, 1.4)},
             "avisos": {"temperatura": "A 0 °C mueren las yemas florales; entre 2 y 5 °C se detiene el crecimiento."}},
        ],
    },
    "lechuga": {
        "nombre": "Lechuga y hojas",
        "descripcion": "En hidroponía la clave es el agua: temperatura entre 18 y 24 °C para que las raíces tengan oxígeno, y pH entre 5,5 y 6,0.",
        "sistema": "Hidroponía NFT o raíz flotante",
        "fuentes": [3, 8],
        "etapas": [
            {"nombre": "Almácigo", "dias": 20, "luz": 14,
             "rangos": {"temperatura": (10, 20), "humedad": (60, 80), "vpd": (0.35, 0.7), "co2": _CO2,
                        "ph": (5.5, 6.0), "ec": (1.0, 1.6), "temp_solucion": (18, 24)},
             "avisos": {"temperatura": "La germinación es óptima entre 18 y 20 °C.",
                        "temp_solucion": "Mantener el agua entre 18 y 24 °C; con agua caliente baja el oxígeno para las raíces."}},
            {"nombre": "Crecimiento", "dias": 30, "luz": 14,
             "rangos": {"temperatura": (10, 20), "humedad": (60, 80), "vpd": (0.35, 0.7), "co2": _CO2,
                        "ph": (5.5, 6.0), "ec": (1.0, 1.6), "temp_solucion": (18, 24)},
             "avisos": {"temp_solucion": "Mantener el agua entre 18 y 24 °C; con agua caliente baja el oxígeno para las raíces."}},
        ],
    },
    "albahaca": {
        "nombre": "Albahaca y aromáticas",
        "descripcion": "Muy sensible al frío: no tolera heladas. El sistema vigila las noches y la temperatura del agua.",
        "sistema": "Hidroponía NFT",
        "fuentes": [3, 10],
        "etapas": [
            {"nombre": "Almácigo", "dias": 15, "luz": 14,
             "rangos": {"temperatura": (16, 30), "humedad": (60, 70), "vpd": (0.8, 1.1), "co2": _CO2,
                        "ph": (5.5, 6.0), "ec": (1.8, 2.2), "temp_solucion": (18, 24)},
             "avisos": {"temperatura": "No tolera heladas ni temperaturas bajo 0 °C."}},
            {"nombre": "Crecimiento y corte", "dias": 45, "luz": 14,
             "rangos": {"temperatura": (16, 30), "humedad": (60, 70), "vpd": (0.8, 1.1), "co2": _CO2,
                        "ph": (5.5, 6.0), "ec": (1.8, 2.2), "temp_solucion": (18, 24)},
             "avisos": {"temperatura": "No tolera heladas ni temperaturas bajo 0 °C.",
                        "temp_solucion": "Mantener el agua entre 18 y 24 °C."}},
        ],
    },
}


def duracion_total(clave: str) -> int:
    return sum(e["dias"] for e in CATALOGO[clave]["etapas"])


def validar_catalogo() -> list[str]:
    """Chequeos de consistencia (los usa la suite de pruebas)."""
    errores = []
    for clave, c in CATALOGO.items():
        for e in c["etapas"]:
            for var in ("temperatura", "humedad", "vpd", "ph", "ec"):
                if var not in e["rangos"]:
                    errores.append(f"{clave}/{e['nombre']}: falta {var}")
            for var, (mn, mx) in e["rangos"].items():
                if mn >= mx:
                    errores.append(f"{clave}/{e['nombre']}: rango inválido en {var}")
        for f in c["fuentes"]:
            if f not in FUENTES:
                errores.append(f"{clave}: fuente {f} inexistente")
    return errores
