"""Traduce los datos técnicos a lenguaje simple para el productor.

Todo es Python puro: recibe valores y rangos, devuelve textos y números listos
para mostrar. Así se puede probar sin la web y reutilizar en alertas por Telegram.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Textos por variable: nombre simple, qué es, y qué significa estar bajo o alto.
INFO = {
    "vpd": {
        "nombre": "Sequedad del aire (VPD)",
        "corto": "VPD",
        "que_es": "Mide qué tan seco está el aire para la planta. Combina temperatura y humedad en un solo número: es el que mejor indica si la planta está cómoda.",
        "bajo": ("Aire muy húmedo", "La planta transpira poco y aumenta el riesgo de hongos."),
        "alto": ("Aire muy seco", "La planta pierde agua de más y se estresa."),
        "consejo_bajo": "Ventilar o subir un poco la temperatura.",
        "consejo_alto": "Bajar la temperatura o subir la humedad.",
        "palabras_escala": ("Muy húmedo", "Ideal", "Muy seco"),
    },
    "temperatura": {
        "nombre": "Temperatura",
        "corto": "Temp.",
        "que_es": "Temperatura del aire a la altura de las plantas.",
        "bajo": ("Hace frío", "El crecimiento se frena."),
        "alto": ("Hace calor", "La planta se estresa y consume más agua."),
        "consejo_bajo": "Encender la calefacción o reducir la ventilación.",
        "consejo_alto": "Ventilar más.",
        "palabras_escala": ("Frío", "Ideal", "Calor"),
    },
    "humedad": {
        "nombre": "Humedad del aire",
        "corto": "HR",
        "que_es": "Cuánta agua tiene el aire, en porcentaje de lo máximo que puede tener a esa temperatura.",
        "bajo": ("Aire seco", "Las hojas pierden agua rápido."),
        "alto": ("Aire muy húmedo", "Riesgo de hongos y moho."),
        "consejo_bajo": "Reducir la ventilación o humidificar.",
        "consejo_alto": "Ventilar.",
        "palabras_escala": ("Seco", "Ideal", "Húmedo"),
    },
    "co2": {
        "nombre": "CO₂ (aire fresco)",
        "corto": "CO₂",
        "que_es": "Dióxido de carbono: es el alimento de la planta en la fotosíntesis. También indica si el aire se renueva.",
        "bajo": ("CO₂ bajo", "La planta tiene menos con qué crecer."),
        "alto": ("Aire viciado", "El aire casi no se renueva."),
        "consejo_bajo": "Renovar el aire.",
        "consejo_alto": "Ventilar.",
        "palabras_escala": ("Bajo", "Ideal", "Alto"),
    },
    "ph": {
        "nombre": "pH del agua de riego",
        "corto": "pH",
        "que_es": "Acidez de la solución nutritiva. Fuera de rango, las raíces no pueden absorber bien algunos nutrientes.",
        "bajo": ("Agua muy ácida", "Las raíces absorben mal algunos nutrientes."),
        "alto": ("Agua poco ácida", "Las raíces absorben mal algunos nutrientes."),
        "consejo_bajo": "Corregir el pH hacia arriba.",
        "consejo_alto": "Corregir el pH hacia abajo.",
        "palabras_escala": ("Ácido", "Ideal", "Alcalino"),
    },
    "ec": {
        "nombre": "Nutrientes en el agua",
        "corto": "EC",
        "que_es": "Conductividad eléctrica: indica cuántos nutrientes tiene la solución.",
        "bajo": ("Pocos nutrientes", "La planta puede quedarse con hambre."),
        "alto": ("Demasiados nutrientes", "Riesgo de quemar las raíces."),
        "consejo_bajo": "Agregar nutrientes a la solución.",
        "consejo_alto": "Diluir la solución con agua.",
        "palabras_escala": ("Bajo", "Ideal", "Alto"),
    },
    "temp_hoja": {"nombre": "Temperatura de hoja", "corto": "T. hoja",
                  "que_es": "Temperatura de la superficie de las hojas, medida con un sensor infrarrojo. Permite calcular el VPD con más precisión."},
    "temp_solucion": {"nombre": "Temperatura del agua", "corto": "T. agua",
                      "que_es": "Temperatura de la solución nutritiva. Si sube mucho, el agua tiene menos oxígeno para las raíces."},
    "luz": {"nombre": "Luz", "corto": "Luz", "que_es": "Intensidad de luz. Sirve para confirmar que las lámparas encendieron."},
}

# Orden de importancia para el resumen general
PRIORIDAD = ["vpd", "temperatura", "humedad", "ph", "ec", "co2"]


@dataclass
class Explicacion:
    variable: str
    nivel: str          # "ok", "atencion", "problema", "sin-dato"
    etiqueta: str       # "Ideal", "Un poco alto", "Muy alto"...
    titulo: str = ""
    detalle: str = ""
    consejo: str = ""
    lado: str = ""      # "bajo" o "alto"


def explicar(variable: str, valor: float | None, rango: tuple[float, float] | None) -> Explicacion:
    if valor is None:
        return Explicacion(variable, "sin-dato", "Sin datos")
    if not rango or variable not in INFO or "bajo" not in INFO[variable]:
        return Explicacion(variable, "ok", "")
    minimo, maximo = rango
    if minimo <= valor <= maximo:
        return Explicacion(variable, "ok", "Ideal")
    lado = "bajo" if valor < minimo else "alto"
    ancho = maximo - minimo
    distancia = (minimo - valor) if lado == "bajo" else (valor - maximo)
    grave = distancia > ancho * 0.25
    info = INFO[variable]
    titulo, detalle = info[lado]
    etiqueta = ("Muy " if grave else "Un poco ") + ("bajo" if lado == "bajo" else "alto")
    return Explicacion(variable, "problema" if grave else "atencion", etiqueta,
                       titulo, detalle, info[f"consejo_{lado}"], lado)


@dataclass
class Diagnostico:
    estado: str                         # "ok", "atencion", "problema"
    titulo: str
    resumen: str
    problemas: list = field(default_factory=list)


def diagnostico_general(explicaciones: list[Explicacion], ventilando: bool = False,
                        modo_auto: bool = True) -> Diagnostico:
    """Arma el mensaje principal del panel a partir de las explicaciones por variable."""
    orden = {v: i for i, v in enumerate(PRIORIDAD)}
    problemas = sorted(
        [e for e in explicaciones if e.nivel in ("atencion", "problema")],
        key=lambda e: (e.nivel != "problema", orden.get(e.variable, 99)),
    )
    if not problemas:
        return Diagnostico("ok", "Todo en orden",
                           "Las condiciones están dentro de lo ideal para esta etapa del cultivo.")
    principal = problemas[0]
    estado = "problema" if principal.nivel == "problema" else "atencion"
    resumen = f"{principal.detalle} "
    if principal.variable in ("vpd", "humedad", "temperatura", "co2") and modo_auto:
        resumen += "El control automático ya está actuando." if ventilando or principal.lado == "bajo" \
            else "El control automático está ajustando la ventilación."
    else:
        resumen += f"Sugerencia: {principal.consejo[0].lower()}{principal.consejo[1:]}"
    otros = len(problemas) - 1
    if otros:
        resumen += f" Hay {otros} {'variable más' if otros == 1 else 'variables más'} para revisar."
    return Diagnostico(estado, principal.titulo, resumen.strip(), problemas)


def puntaje(porcentajes_en_rango: list[float | None]) -> int | None:
    """Puntaje 0–100 del ambiente: promedio del tiempo en rango de las variables clave."""
    validos = [p for p in porcentajes_en_rango if p is not None]
    if not validos:
        return None
    return round(sum(validos) / len(validos))


def calificar(p: int | None) -> str:
    if p is None:
        return "Sin datos"
    if p >= 80:
        return "Muy bueno"
    if p >= 60:
        return "Bueno"
    if p >= 40:
        return "Regular"
    return "Malo"


def desvio_normalizado(valor: float, rango: tuple[float, float]) -> float:
    """0 si está en rango; negativo por debajo y positivo por encima,
    medido en anchos del rango y limitado a [-1, 1]."""
    minimo, maximo = rango
    ancho = (maximo - minimo) or 1.0
    if valor < minimo:
        return max(-1.0, (valor - minimo) / ancho)
    if valor > maximo:
        return min(1.0, (valor - maximo) / ancho)
    return 0.0


def mapa_calor(filas: list[tuple[datetime, float, tuple[float, float] | None]]):
    """Matriz días × horas con el desvío promedio respecto del rango.

    filas: (momento local, valor, rango vigente). Devuelve (dias, horas, z, promedios).
    """
    suma = defaultdict(float)
    suma_valor = defaultdict(float)
    cuenta = defaultdict(int)
    for momento, valor, rango in filas:
        if not rango:
            continue
        clave = (momento.date(), momento.hour)
        suma[clave] += desvio_normalizado(valor, rango)
        suma_valor[clave] += valor
        cuenta[clave] += 1
    dias = sorted({d for d, _ in cuenta})
    horas = list(range(24))
    z, promedios = [], []
    for d in dias:
        fila_z, fila_v = [], []
        for h in horas:
            n = cuenta.get((d, h))
            fila_z.append(round(suma[(d, h)] / n, 3) if n else None)
            fila_v.append(round(suma_valor[(d, h)] / n, 2) if n else None)
        z.append(fila_z)
        promedios.append(fila_v)
    return dias, horas, z, promedios


def resumen_texto(variable: str, filas: list[tuple[datetime, float, tuple[float, float] | None]],
                  unidad: str = "") -> list[str]:
    """Frases simples que resumen un período: tiempo en rango, hacia dónde se sale y cuándo."""
    con_rango = [(m, v, r) for m, v, r in filas if r]
    if not filas:
        return ["No hay lecturas en este período."]
    info = INFO.get(variable, {})
    frases = []
    if con_rango:
        dentro = sum(1 for _, v, r in con_rango if r[0] <= v <= r[1])
        bajos = sum(1 for _, v, r in con_rango if v < r[0])
        altos = len(con_rango) - dentro - bajos
        pct = round(100 * dentro / len(con_rango))
        frases.append(f"Estuvo en el rango ideal el {pct}% del tiempo.")
        if bajos or altos:
            lado = "bajo" if bajos >= altos else "alto"
            titulo = info.get(lado, ("Por debajo" if lado == "bajo" else "Por encima", ""))[0]
            pct_lado = round(100 * max(bajos, altos) / len(con_rango))
            frases.append(f"Cuando se salió, fue sobre todo por «{titulo.lower()}» ({pct_lado}% del tiempo).")
            # Franja horaria más problemática
            fuera_por_hora = defaultdict(lambda: [0, 0])
            for m, v, r in con_rango:
                fuera_por_hora[m.hour][1] += 1
                fuera_por_hora[m.hour][0] += not (r[0] <= v <= r[1])
            tasas = {h: f / t for h, (f, t) in fuera_por_hora.items() if t}
            peor = max(tasas, key=tasas.get)
            if tasas[peor] >= 0.3:
                inicio, fin = peor, peor
                while (inicio - 1) % 24 in tasas and tasas[(inicio - 1) % 24] >= 0.6 * tasas[peor] and (inicio - 1) % 24 != fin:
                    inicio = (inicio - 1) % 24
                while (fin + 1) % 24 in tasas and tasas[(fin + 1) % 24] >= 0.6 * tasas[peor] and (fin + 1) % 24 != inicio:
                    fin = (fin + 1) % 24
                frases.append(f"Las horas más complicadas son de {inicio} a {(fin + 1) % 24} h.")
    maximo = max(filas, key=lambda f: f[1])
    minimo = min(filas, key=lambda f: f[1])
    frases.append(
        f"Máximo {maximo[1]:.2f} {unidad} ({maximo[0]:%d/%m %H:%M}); mínimo {minimo[1]:.2f} {unidad} ({minimo[0]:%d/%m %H:%M})."
        .replace(" )", ")"))
    return frases


def frase_accion(actuador: str, encendido: bool, motivo: str) -> str:
    verbo = "se encendió" if encendido else "se apagó"
    texto = f"{actuador} {verbo}"
    if motivo:
        texto += f": {motivo}"
    return texto


def puntajes_diarios(filas_por_variable: dict) -> dict:
    """Puntaje 0–100 de cada día: promedio, entre variables, del % de lecturas en rango.

    filas_por_variable: {variable: [(momento local, valor, rango), ...]}
    Devuelve {fecha: puntaje}.
    """
    por_dia = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for variable, filas in filas_por_variable.items():
        for momento, valor, rango in filas:
            if not rango:
                continue
            celda = por_dia[momento.date()][variable]
            celda[1] += 1
            celda[0] += rango[0] <= valor <= rango[1]
    resultado = {}
    for dia, variables in por_dia.items():
        resultado[dia] = puntaje([100 * d / t for d, t in variables.values() if t])
    return dict(sorted(resultado.items()))


def promedio_puntajes(puntajes: dict, desde=None) -> int | None:
    valores = [p for d, p in puntajes.items() if p is not None and (desde is None or d >= desde)]
    return round(sum(valores) / len(valores)) if valores else None


def franjas_horarias(filas, ahora: datetime, horas: int = 24):
    """Promedio por hora de las últimas `horas`, con su desvío respecto del rango.

    filas: [(momento local, valor, rango)]. Devuelve una lista ordenada de la hora más
    vieja a la actual: {"hora": "14 h", "valor": 1.02, "z": 0.0} (valor/z None si no hay datos).
    """
    inicio = ahora.replace(minute=0, second=0, microsecond=0)
    claves = [inicio.replace(tzinfo=None) - timedelta(hours=horas - 1 - i) for i in range(horas)]
    suma = defaultdict(float)
    suma_z = defaultdict(float)
    cuenta = defaultdict(int)
    for momento, valor, rango in filas:
        clave = momento.replace(minute=0, second=0, microsecond=0, tzinfo=None)
        suma[clave] += valor
        cuenta[clave] += 1
        if rango:
            suma_z[clave] += desvio_normalizado(valor, rango)
    salida = []
    for c in claves:
        n = cuenta.get(c)
        salida.append({
            "hora": f"{c.hour} h",
            "valor": round(suma[c] / n, 2) if n else None,
            "z": round(suma_z[c] / n, 3) if n else None,
        })
    return salida


# Qué equipo corrige cada desvío. Si la sala no lo tiene, el sistema no puede
# actuar: avisa y recomienda. Nadie está obligado a tener todo; el sistema se
# adapta a la instalación de cada productor.
NOMBRES_EQUIPO = {
    "extractor": "extractor", "calefactor": "calefacción", "humidificador": "humidificador",
    "deshumidificador": "deshumidificador", "riego": "riego automático", "luz": "luces",
    "ventilador": "ventiladores internos",
}
CORRECCIONES = [
    # (variable, lado, equipos que lo corrigen, título, consecuencia)
    ("vpd", "alto", {"humidificador"}, "Falta un humidificador",
     "El aire está seco y no hay con qué humedecerlo: la planta se estresa y se favorecen plagas como la arañuela."),
    ("humedad", "bajo", {"humidificador"}, "Falta un humidificador",
     "El aire está seco y no hay con qué humedecerlo: la planta se estresa y se favorecen plagas como la arañuela."),
    ("vpd", "bajo", {"extractor", "deshumidificador"}, "Falta ventilación o deshumidificador",
     "El aire está húmedo y no hay con qué secarlo: aumenta el riesgo de hongos."),
    ("humedad", "alto", {"extractor", "deshumidificador"}, "Falta ventilación o deshumidificador",
     "El aire está húmedo y no hay con qué secarlo: aumenta el riesgo de hongos."),
    ("temperatura", "bajo", {"calefactor"}, "Falta calefacción",
     "Hace frío y no hay con qué calentar: el crecimiento se frena."),
    ("humedad", "alto", {"ventilador"}, "Faltan ventiladores internos",
     "Sin movimiento de aire se forman bolsones de humedad entre las plantas y aparecen hongos."),
    ("temperatura", "alto", {"extractor"}, "Falta ventilación",
     "Hace calor y no hay con qué ventilar: la planta se estresa."),
]


def recomendaciones(explicaciones, equipos: set[str]) -> list[dict]:
    """Avisos para lo que el sistema no puede corregir solo por falta de equipo,
    y correcciones que siempre son manuales (solución nutritiva)."""
    salida, vistos = [], set()
    for e in explicaciones:
        if e.nivel not in ("atencion", "problema"):
            continue
        for variable, lado, necesarios, titulo, texto in CORRECCIONES:
            if e.variable == variable and e.lado == lado and not (necesarios & equipos) and titulo not in vistos:
                vistos.add(titulo)
                salida.append({"titulo": titulo, "texto": texto, "variable": variable, "tipo": "equipo",
                               "equipos": sorted(NOMBRES_EQUIPO[n] for n in necesarios)})
        if e.variable in ("ph", "ec") and e.titulo not in vistos:
            vistos.add(e.titulo)
            salida.append({"titulo": e.titulo, "texto": f"{e.detalle} {e.consejo}", "variable": e.variable,
                           "tipo": "manual", "equipos": []})
    return salida
