"""Consultas y cálculos sobre los datos: estado actual, series, cumplimiento."""
from collections import defaultdict
from datetime import timedelta
import statistics

from django.utils import timezone

from .models import VARIABLES, AccionActuador, Lectura

VARIABLES_PANEL = ["vpd", "temperatura", "humedad", "co2", "temp_hoja", "ph", "ec", "temp_solucion"]
VARIABLES_CUMPLIMIENTO = ["vpd", "temperatura", "humedad", "co2", "ph", "ec"]


def ultimas_lecturas(sala, variables=None):
    variables = variables or list(VARIABLES)
    resultado = {}
    for v in variables:
        lectura = sala.lecturas.filter(variable=v).order_by("-momento").first()
        if lectura:
            resultado[v] = lectura
    return resultado


def rangos_de_etapa(etapa):
    if not etapa:
        return {}
    return {r.variable: (r.minimo, r.maximo) for r in etapa.rangos.all()}


def estado_variable(valor, rango):
    if rango is None or valor is None:
        return "sin-rango"
    minimo, maximo = rango
    if minimo <= valor <= maximo:
        return "ok"
    margen = (maximo - minimo) * 0.25
    if minimo - margen <= valor <= maximo + margen:
        return "atencion"
    return "fuera"


def tarjetas(sala):
    """Datos de las tarjetas del panel: último valor de cada variable frente a la receta."""
    ciclo = sala.ciclo_activo()
    etapa = ciclo.etapa_en() if ciclo else None
    rangos = rangos_de_etapa(etapa)
    if ciclo and ciclo.fertilizacion == "organica":
        rangos.pop("ph", None)
        rangos.pop("ec", None)
    ultimas = ultimas_lecturas(sala, VARIABLES_PANEL)
    salida = []
    for v in VARIABLES_PANEL:
        etiqueta, unidad, decimales = VARIABLES[v]
        lectura = ultimas.get(v)
        valor = lectura.valor if lectura else None
        rango = rangos.get(v)
        salida.append({
            "variable": v,
            "etiqueta": etiqueta,
            "unidad": unidad,
            "valor": round(valor, decimales) if valor is not None else None,
            "texto": f"{valor:.{decimales}f}" if valor is not None else "—",
            "minimo": rango[0] if rango else None,
            "maximo": rango[1] if rango else None,
            "estado": estado_variable(valor, rango),
            "momento": lectura.momento.isoformat() if lectura else None,
        })
    return salida


def serie(sala, variable, desde, hasta, puntos=400):
    """Serie temporal reducida a `puntos` promedios, para graficar sin saturar el navegador."""
    filas = list(
        sala.lecturas.filter(variable=variable, momento__gte=desde, momento__lte=hasta)
        .order_by("momento").values_list("momento", "valor")
    )
    if len(filas) <= puntos:
        return [f[0] for f in filas], [f[1] for f in filas]
    tamano = len(filas) / puntos
    xs, ys = [], []
    for i in range(puntos):
        grupo = filas[int(i * tamano):int((i + 1) * tamano)]
        if grupo:
            xs.append(grupo[len(grupo) // 2][0])
            ys.append(sum(g[1] for g in grupo) / len(grupo))
    return xs, ys


def bandas_receta(ciclo, variable, desde, hasta):
    """Rangos objetivo por etapa, recortados a la ventana pedida (para la banda del gráfico)."""
    if not ciclo:
        return []
    bandas = []
    for etapa, inicio, fin in ciclo.ventanas_etapas():
        ini, fi = max(inicio, desde), min(fin, hasta)
        rango = etapa.rango(variable)
        if ini < fi and rango:
            bandas.append({"inicio": ini.isoformat(), "fin": fi.isoformat(),
                           "minimo": rango[0], "maximo": rango[1], "etapa": etapa.nombre})
    return bandas


def estadisticas(sala, ciclo, variable, desde, hasta):
    """Tiempo en rango (%), media y desvío de una variable en una ventana de tiempo.

    El rango de cada lectura es el de la etapa del ciclo vigente en ese momento.
    """
    dentro = total = 0
    valores = []
    for etapa, inicio, fin in ciclo.ventanas_etapas():
        ini, fi = max(inicio, desde), min(fin, hasta)
        if ini >= fi:
            continue
        rango = etapa.rango(variable)
        datos = list(sala.lecturas.filter(variable=variable, momento__gte=ini, momento__lt=fi)
                     .values_list("valor", flat=True))
        valores += datos
        if rango:
            dentro += sum(1 for x in datos if rango[0] <= x <= rango[1])
            total += len(datos)
    return {
        "variable": variable,
        "etiqueta": VARIABLES[variable][0],
        "unidad": VARIABLES[variable][1],
        "en_rango": round(100 * dentro / total, 1) if total else None,
        "media": round(statistics.fmean(valores), 2) if valores else None,
        "desvio": round(statistics.pstdev(valores), 2) if len(valores) > 1 else None,
        "n": len(valores),
    }


def cumplimiento_por_etapa(ciclo):
    """Cumplimiento del plan de cultivo: % de tiempo en rango por etapa y variable.

    Una etapa puede tener más de un tramo si el productor volvió atrás; se muestra cada tramo.
    """
    filas = []
    ahora = timezone.now()
    alcanzadas = set()
    for etapa, inicio, fin in ciclo.ventanas_etapas():
        if inicio > ahora:
            continue
        alcanzadas.add(etapa.id)
        fin_real = min(fin, ciclo.fecha_fin or ahora)
        valores = [estadisticas(ciclo.sala, ciclo, v, inicio, fin_real) for v in VARIABLES_CUMPLIMIENTO]
        filas.append({"etapa": etapa, "inicio": inicio, "fin": fin_real, "futura": False, "valores": valores})
    for etapa in ciclo.receta.etapas.all():
        if etapa.id not in alcanzadas:
            filas.append({"etapa": etapa, "inicio": None, "fin": None, "futura": True, "valores": []})
    return filas


def resumen_periodos(sala, ciclo):
    """Comparación de los períodos del experimento (Capítulo 7)."""
    resumen = []
    ahora = timezone.now()
    for periodo in sala.periodos.all():
        fin = periodo.fin or ahora
        dias = max((fin - periodo.inicio).total_seconds() / 86400, 1e-6)
        manuales = AccionActuador.objects.filter(
            actuador__sala=sala, origen="manual", momento__gte=periodo.inicio, momento__lt=fin
        ).count()
        resumen.append({
            "periodo": periodo,
            "dias": round(dias, 1),
            "estadisticas": [estadisticas(sala, ciclo, v, periodo.inicio, fin) for v in ["vpd", "temperatura", "humedad"]],
            "manuales_por_dia": round(manuales / dias, 2),
            "alertas": sala.alertas.filter(momento__gte=periodo.inicio, momento__lt=fin).count(),
        })
    return resumen


def comparacion(sala, ciclo):
    """Antes (equipos a horario fijo) vs. después (control automático), en pocas cifras.

    Devuelve None si todavía no hay los dos períodos con datos."""
    if not ciclo:
        return None
    resumen = resumen_periodos(sala, ciclo)
    antes = next((r for r in resumen if r["periodo"].modo == "horario"), None)
    despues = next((r for r in reversed(resumen) if r["periodo"].modo == "lazo_cerrado"), None)
    if not antes or not despues:
        return None
    a, d = antes["estadisticas"][0]["en_rango"], despues["estadisticas"][0]["en_rango"]
    if a is None or d is None:
        return None
    return {"antes": round(a), "despues": round(d), "mejora": round(d - a), "diferencia": abs(round(d - a)),
            "manuales_antes": antes["manuales_por_dia"], "manuales_despues": despues["manuales_por_dia"],
            "dias_antes": antes["dias"], "dias_despues": despues["dias"]}


def en_rango_diario(sala, ciclo, variable, desde, hasta):
    """% de tiempo en rango por día (para el gráfico del experimento)."""
    conteo = defaultdict(lambda: [0, 0])
    for etapa, inicio, fin in ciclo.ventanas_etapas():
        ini, fi = max(inicio, desde), min(fin, hasta)
        if ini >= fi:
            continue
        rango = etapa.rango(variable)
        if not rango:
            continue
        for momento, valor in sala.lecturas.filter(variable=variable, momento__gte=ini, momento__lt=fi) \
                .values_list("momento", "valor"):
            dia = timezone.localtime(momento).date()
            conteo[dia][1] += 1
            conteo[dia][0] += rango[0] <= valor <= rango[1]
    dias = sorted(conteo)
    return [d.isoformat() for d in dias], [round(100 * conteo[d][0] / conteo[d][1], 1) for d in dias]


def ventana(horas):
    hasta = timezone.now()
    return hasta - timedelta(hours=horas), hasta


# ---------------------------------------------------------------- lenguaje simple
from nucleo import diagnostico as dx  # noqa: E402


def filas_con_rango(sala, ciclo, variable, desde, hasta):
    """(momento local, valor, rango vigente) para cada lectura de la ventana."""
    filas = []
    ventanas = ciclo.ventanas_etapas() if ciclo else []
    rangos = {e.id: e.rango(variable) for e, _, _ in ventanas}
    datos = sala.lecturas.filter(variable=variable, momento__gte=desde, momento__lte=hasta) \
        .order_by("momento").values_list("momento", "valor")
    i = 0
    for momento, valor in datos:
        rango = None
        while i < len(ventanas) and momento >= ventanas[i][2]:
            i += 1
        if i < len(ventanas) and ventanas[i][1] <= momento:
            rango = rangos[ventanas[i][0].id]
        filas.append((timezone.localtime(momento), valor, rango))
    return filas


def estado_simple(sala):
    """Diagnóstico general, explicación por variable y puntaje de las últimas 24 h."""
    ciclo = sala.ciclo_activo()
    etapa = ciclo.etapa_en() if ciclo else None
    rangos = rangos_de_etapa(etapa)
    if ciclo and ciclo.fertilizacion == "organica":
        # En orgánico no se controla la solución nutritiva: pH y EC quedan como dato informativo
        rangos.pop("ph", None)
        rangos.pop("ec", None)
    ultimas = ultimas_lecturas(sala, VARIABLES_PANEL)
    explicaciones = {
        v: dx.explicar(v, ultimas[v].valor if v in ultimas else None, rangos.get(v))
        for v in VARIABLES_PANEL
    }
    extractores = sala.actuadores.filter(activo=True, tipo="extractor")
    ventilando = extractores.filter(encendido=True).exists()
    modo_auto = not sala.control_pausado and not sala.actuadores.filter(activo=True, modo="manual").exists()
    diag = dx.diagnostico_general(list(explicaciones.values()), ventilando, modo_auto)
    equipos = set(sala.actuadores.filter(activo=True).values_list("tipo", flat=True))
    recs = dx.recomendaciones(list(explicaciones.values()), equipos)
    if diag.problemas:
        principal = diag.problemas[0]
        falta = next((r for r in recs if r["variable"] == principal.variable and r["tipo"] == "equipo"), None)
        if falta:
            diag.resumen = f"{principal.detalle} {falta['titulo']}: el sistema no puede corregirlo solo."
    if sala.control_pausado:
        diag.resumen += " Atención: el control automático está en pausa."

    puntos = None
    if ciclo:
        desde, hasta = ventana(24)
        puntos = dx.puntaje([estadisticas(sala, ciclo, v, desde, hasta)["en_rango"]
                             for v in ("vpd", "temperatura", "humedad")])
    return {
        "diagnostico": diag,
        "explicaciones": explicaciones,
        "puntaje": puntos,
        "calificacion": dx.calificar(puntos),
        "modo_auto": modo_auto,
        "pausado": sala.control_pausado,
        "recomendaciones": recs,
        "equipos": equipos,
        "avisos": (etapa.avisos or {}) if etapa else {},
    }


def linea_tiempo(ciclo):
    """Etapas del ciclo: las que ya pasaron (con su duración real), la actual y las que vienen.

    Las duraciones de la receta son solo una referencia: el cambio de etapa lo decide el productor.
    """
    if not ciclo:
        return None
    ahora = timezone.now()
    etapas = list(ciclo.receta.etapas.all())
    reales = {}
    actual, inicio_actual = None, None
    for etapa, inicio, fin in ciclo.ventanas_etapas():
        if inicio > ahora:
            continue
        dias = max(0, (min(fin, ahora) - inicio).days)
        reales[etapa.id] = reales.get(etapa.id, 0) + dias
        if inicio <= ahora < fin:
            actual, inicio_actual = etapa, inicio
    dias_en_etapa = (ahora - inicio_actual).days + 1 if inicio_actual else None
    segmentos = []
    for e in etapas:
        if actual and e.id == actual.id:
            estado, dias = "actual", max(dias_en_etapa or 1, 1)
        elif e.id in reales and (not actual or e.orden < actual.orden):
            estado, dias = "pasada", max(reales[e.id], 1)
        else:
            estado, dias = "futura", e.duracion_dias
        segmentos.append({"id": e.id, "nombre": e.nombre, "estimado": e.duracion_dias, "dias": dias,
                          "horas_luz": e.horas_luz, "estado": estado})
    total = sum(s["dias"] if s["estado"] != "futura" else s["estimado"] for s in segmentos) or 1
    for seg in segmentos:
        seg["ancho"] = 100 * (seg["dias"] if seg["estado"] != "futura" else seg["estimado"]) / total
    siguiente = ciclo.etapa_siguiente()
    return {
        "segmentos": segmentos, "dia": ciclo.dia(), "actual": actual,
        "dias_en_etapa": dias_en_etapa,
        "estimado_actual": actual.duracion_dias if actual else None,
        "siguiente": siguiente,
        "cambio_luz": bool(siguiente and actual and siguiente.horas_luz != actual.horas_luz),
        "pasado_estimado": bool(actual and dias_en_etapa and dias_en_etapa > actual.duracion_dias),
    }


def actividad(sala, cantidad=8):
    acciones = AccionActuador.objects.filter(actuador__sala=sala).select_related("actuador")[:cantidad]
    return [{
        "momento": a.momento,
        "texto": dx.frase_accion(a.actuador.nombre, a.encendido, a.motivo),
        "origen": a.get_origen_display(),
        "origen_clave": a.origen,
        "encendido": a.encendido,
    } for a in acciones]


# ---------------------------------------------------------------- recetas y puntajes

from nucleo.recetas import CATALOGO, FUENTES  # noqa: E402


def crear_ciclo_desde_catalogo(sala, clave, codigo_lote, fecha_inicio, cerrar_anterior=True, etapa_inicial=1,
                               fertilizacion="mineral"):
    """Crea la receta (copia editable del catálogo) y el ciclo en una sola operación."""
    from .models import Ciclo, Etapa, RangoObjetivo, Receta

    datos = CATALOGO[clave]
    if cerrar_anterior:
        sala.ciclos.filter(fecha_fin__isnull=True).update(fecha_fin=fecha_inicio)
    receta = Receta.objects.create(
        nombre=f"{datos['nombre']} · {codigo_lote}",
        descripcion=datos["descripcion"],
        cultivo=clave,
        fuentes="\n".join(f"[{n}] {FUENTES[n]}" for n in datos["fuentes"]),
    )
    for orden, e in enumerate(datos["etapas"], start=1):
        etapa = Etapa.objects.create(receta=receta, nombre=e["nombre"], orden=orden,
                                     duracion_dias=e["dias"], horas_luz=e["luz"], avisos=e.get("avisos", {}))
        RangoObjetivo.objects.bulk_create([
            RangoObjetivo(etapa=etapa, variable=v, minimo=mn, maximo=mx) for v, (mn, mx) in e["rangos"].items()
        ])
    ciclo = Ciclo.objects.create(sala=sala, codigo_lote=codigo_lote, cultivo=datos["nombre"],
                                 receta=receta, fecha_inicio=fecha_inicio, fertilizacion=fertilizacion)
    primera = receta.etapas.filter(orden=etapa_inicial).first() or receta.etapas.order_by("orden").first()
    ciclo.cambiar_etapa(primera, momento=fecha_inicio)
    return ciclo


def puntajes_sala(sala, dias=35):
    """Puntaje diario de los últimos `dias` y promedios de hoy, 7 y 30 días."""
    ciclo = sala.ciclo_activo()
    if not ciclo:
        return {"dias": [], "hoy": None, "semana": None, "mes": None}
    hasta = timezone.now()
    desde = max(ciclo.fecha_inicio, hasta - timedelta(days=dias))
    filas = {v: filas_con_rango(sala, ciclo, v, desde, hasta) for v in ("vpd", "temperatura", "humedad")}
    diarios = dx.puntajes_diarios(filas)
    hoy = timezone.localdate()
    return {
        "dias": [{"fecha": d.isoformat(), "puntaje": p, "calificacion": dx.calificar(p)} for d, p in diarios.items()],
        "hoy": diarios.get(hoy),
        "semana": dx.promedio_puntajes(diarios, hoy - timedelta(days=6)),
        "mes": dx.promedio_puntajes(diarios, hoy - timedelta(days=29)),
    }
