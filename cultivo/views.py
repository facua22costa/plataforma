from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from nucleo import diagnostico as dx
from nucleo.drivers import ErrorDriver, crear_driver

from . import servicios
from .forms import CamaraForm, EventoBitacoraForm
from .models import VARIABLES, AccionActuador, Actuador, Alerta, Camara, Ciclo, Sala


def _sala(sala_id=None):
    if sala_id:
        return get_object_or_404(Sala, pk=sala_id)
    return Sala.objects.order_by("id").first()


def _contexto_base(sala):
    return {"sala": sala, "salas": Sala.objects.all()}


@login_required
def panel(request, sala_id=None):
    sala = _sala(sala_id)
    if sala is None:
        return render(request, "cultivo/sin_datos.html")
    ciclo = sala.ciclo_activo()
    etapa = ciclo.etapa_en() if ciclo else None
    contexto = _contexto_base(sala) | {
        "ciclo": ciclo,
        "etapa": etapa,
        "dia": ciclo.dia() if ciclo else None,
        "periodo": sala.periodo_activo(),
        "tarjetas": servicios.tarjetas(sala),
        "actuadores": sala.actuadores.filter(activo=True),
        "alertas": sala.alertas.filter(resuelta=False)[:5],
        "exterior": servicios.ultimas_lecturas(sala, ["temp_exterior", "humedad_exterior"]),
        "simple": servicios.estado_simple(sala),
        "linea": servicios.linea_tiempo(ciclo),
        "actividad": servicios.actividad(sala),
        "novedades": novedades(sala, ciclo),
        "ultima_medicion": sala.lecturas.filter(origen="manual", variable__in=["ph", "ec"]).order_by("-momento").first(),
        "hay_sondas": sala.lecturas.filter(origen__in=["sensor", "simulado"], variable="ph",
                                           momento__gte=timezone.now() - timedelta(hours=2)).exists(),
        "camara": sala.camaras.filter(activa=True).first(),
        "camaras_total": sala.camaras.filter(activa=True).count(),
        "seccion": "panel",
    }
    for t in contexto["tarjetas"]:
        e = contexto["simple"]["explicaciones"].get(t["variable"])
        info = dx.INFO.get(t["variable"], {})
        t["nombre_simple"] = info.get("nombre", t["etiqueta"])
        t["que_es"] = info.get("que_es", "")
        t["etiqueta_estado"] = e.etiqueta if e else ""
        t["titulo_estado"] = e.titulo if e else ""
        t["aviso"] = contexto["simple"]["avisos"].get(t["variable"], "")
    return render(request, "cultivo/panel.html", contexto)


@login_required
def api_estado(request, sala_id):
    sala = _sala(sala_id)
    simple = servicios.estado_simple(sala)
    tarjetas = servicios.tarjetas(sala)
    for t in tarjetas:
        e = simple["explicaciones"].get(t["variable"])
        t["etiqueta_estado"] = e.etiqueta if e else ""
    d = simple["diagnostico"]
    return JsonResponse({
        "momento": timezone.now().isoformat(),
        "diagnostico": {"estado": d.estado, "titulo": d.titulo, "resumen": d.resumen},
        "puntaje": simple["puntaje"], "calificacion": simple["calificacion"],
        "tarjetas": tarjetas,
        "actuadores": [
            {"id": a.id, "nombre": a.nombre, "encendido": a.encendido, "modo": a.modo}
            for a in sala.actuadores.filter(activo=True)
        ],
    })


@login_required
def api_serie(request, sala_id):
    sala = _sala(sala_id)
    horas = float(request.GET.get("horas", 24))
    desde, hasta = servicios.ventana(horas)
    if request.GET.get("desde"):
        desde = timezone.make_aware(datetime.fromisoformat(request.GET["desde"]))
    if request.GET.get("hasta"):
        hasta = timezone.make_aware(datetime.fromisoformat(request.GET["hasta"])) + timedelta(days=1)
    variables = [v for v in request.GET.get("variables", "vpd").split(",") if v in VARIABLES]
    ciclo = sala.ciclo_activo()
    datos = {}
    for v in variables:
        xs, ys = servicios.serie(sala, v, desde, hasta)
        datos[v] = {
            "x": [timezone.localtime(x).isoformat() for x in xs],
            "y": [round(y, 3) for y in ys],
            "etiqueta": VARIABLES[v][0],
            "unidad": VARIABLES[v][1],
            "bandas": servicios.bandas_receta(ciclo, v, desde, hasta),
        }
    return JsonResponse({"series": datos})


@login_required
def historial(request, sala_id=None):
    sala = _sala(sala_id)
    contexto = _contexto_base(sala) | {
        "variables": [(k, v[0]) for k, v in VARIABLES.items()],
        "comparacion": servicios.comparacion(sala, sala.ciclo_activo()),
        "seccion": "historial",
    }
    return render(request, "cultivo/historial.html", contexto)


@login_required
@require_POST
def actuador_comando(request, pk):
    actuador = get_object_or_404(Actuador, pk=pk)
    comando = request.POST.get("comando")
    if comando == "auto":
        actuador.modo, actuador.manual_hasta = "auto", None
        actuador.save()
        messages.info(request, f"{actuador.nombre} vuelve a modo automático.")
    elif comando in ("encender", "apagar"):
        encender = comando == "encender"
        try:
            crear_driver(actuador.driver, actuador.config).aplicar(encender)
        except ErrorDriver as exc:
            messages.error(request, f"No se pudo comandar {actuador.nombre}: {exc}")
            return redirect("panel_sala", sala_id=actuador.sala_id)
        actuador.modo, actuador.manual_hasta = "manual", None
        actuador.encendido = encender
        actuador.save()
        AccionActuador.objects.create(
            actuador=actuador, momento=timezone.now(), encendido=encender,
            origen="manual", motivo=f"comando manual de {request.user.username}",
        )
        messages.success(request, f"{actuador.nombre} {'encendido' if encender else 'apagado'} (modo manual).")
    return redirect("panel_sala", sala_id=actuador.sala_id)


@login_required
@require_POST
def alerta_resolver(request, pk):
    alerta = get_object_or_404(Alerta, pk=pk)
    alerta.resuelta = True
    alerta.save()
    return redirect("panel_sala", sala_id=alerta.sala_id)


@login_required
def ciclos(request, sala_id=None):
    sala = _sala(sala_id)
    contexto = _contexto_base(sala) | {"ciclos": sala.ciclos.all(), "seccion": "ciclos"}
    return render(request, "cultivo/ciclos.html", contexto)


@login_required
def ciclo_detalle(request, pk):
    ciclo = get_object_or_404(Ciclo, pk=pk)
    contexto = _contexto_base(ciclo.sala) | {
        "ciclo": ciclo,
        "etapa": ciclo.etapa_en() if ciclo.activo else None,
        "cumplimiento": servicios.cumplimiento_por_etapa(ciclo),
        "eventos": ciclo.eventos.all()[:30],
        "cosechas": ciclo.cosechas.all(),
        "seccion": "ciclos",
    }
    return render(request, "cultivo/ciclo_detalle.html", contexto)


@login_required
def bitacora_nuevo(request, ciclo_id):
    ciclo = get_object_or_404(Ciclo, pk=ciclo_id)
    inicial = {"momento": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "tipo": request.GET.get("tipo", "riego")}
    form = EventoBitacoraForm(request.POST or None, request.FILES or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        evento = form.save(commit=False)
        evento.ciclo = ciclo
        evento.usuario = request.user
        evento.save()
        messages.success(request, "Evento registrado en la bitácora.")
        return redirect("ciclo_detalle", pk=ciclo.pk)
    contexto = _contexto_base(ciclo.sala) | {"form": form, "ciclo": ciclo, "seccion": "ciclos"}
    return render(request, "cultivo/bitacora_form.html", contexto)


@login_required
def experimento(request, sala_id=None):
    sala = _sala(sala_id)
    ciclo = sala.ciclo_activo()
    resumen = servicios.resumen_periodos(sala, ciclo) if ciclo else []
    contexto = _contexto_base(sala) | {"ciclo": ciclo, "resumen": resumen, "seccion": "experimento"}
    return render(request, "cultivo/experimento.html", contexto)


@login_required
def api_experimento(request, sala_id):
    sala = _sala(sala_id)
    ciclo = sala.ciclo_activo()
    if not ciclo:
        return JsonResponse({"dias": [], "series": {}, "periodos": []})
    series = {}
    dias = []
    for v in ["vpd", "temperatura", "humedad"]:
        dias, valores = servicios.en_rango_diario(sala, ciclo, v, ciclo.fecha_inicio, timezone.now())
        series[v] = {"y": valores, "etiqueta": VARIABLES[v][0]}
    periodos = [
        {"nombre": p.nombre, "modo": p.modo,
         "inicio": timezone.localtime(p.inicio).date().isoformat(),
         "fin": timezone.localtime(p.fin or timezone.now()).date().isoformat()}
        for p in sala.periodos.all()
    ]
    return JsonResponse({"dias": dias, "series": series, "periodos": periodos})


ACCIONES_RAPIDAS = {
    # clave: (tipo de actuador, encender, minutos, mensaje)
    "ventilar": ("extractor", True, 15, "Ventilando con todos los extractores durante 15 minutos."),
    "pausar": ("extractor", False, 30, "Ventilación pausada por 30 minutos."),
    "calentar": ("calefactor", True, 30, "Calefactor encendido durante 30 minutos."),
}


@login_required
@require_POST
def accion_rapida(request, sala_id):
    sala = _sala(sala_id)
    accion = request.POST.get("accion")
    ahora = timezone.now()
    if accion == "auto":
        sala.actuadores.filter(activo=True).update(modo="auto", manual_hasta=None)
        messages.success(request, "Todo vuelve a control automático.")
        return redirect("panel_sala", sala_id=sala.id)
    if accion not in ACCIONES_RAPIDAS:
        return redirect("panel_sala", sala_id=sala.id)
    tipo, encender, minutos, mensaje = ACCIONES_RAPIDAS[accion]
    actuadores = list(sala.actuadores.filter(activo=True, tipo=tipo))
    if not actuadores:
        messages.error(request, "No hay actuadores de ese tipo configurados.")
        return redirect("panel_sala", sala_id=sala.id)
    for a in actuadores:
        try:
            crear_driver(a.driver, a.config).aplicar(encender)
        except ErrorDriver as exc:
            messages.error(request, f"{a.nombre} no respondió: {exc}")
            continue
        a.modo, a.encendido = "manual", encender
        a.manual_hasta = ahora + timedelta(minutes=minutos)
        a.save()
        AccionActuador.objects.create(actuador=a, momento=ahora, encendido=encender, origen="manual",
                                      motivo=f"acción rápida de {request.user.username} ({minutos} min)")
    messages.success(request, mensaje + " Después vuelve solo a automático.")
    return redirect("panel_sala", sala_id=sala.id)


def _ventana_get(request):
    dias = request.GET.get("dias")
    hasta = timezone.now()
    if dias == "ciclo":
        return None, hasta
    return hasta - timedelta(days=float(dias or 7)), hasta


@login_required
def api_resumen(request, sala_id):
    """Frases simples y mapa de calor (días × horas) de una variable."""
    sala = _sala(sala_id)
    variable = request.GET.get("variable", "vpd")
    if variable not in VARIABLES:
        variable = "vpd"
    ciclo = sala.ciclo_activo()
    desde, hasta = _ventana_get(request)
    if desde is None:
        desde = ciclo.fecha_inicio if ciclo else hasta - timedelta(days=30)
    filas = servicios.filas_con_rango(sala, ciclo, variable, desde, hasta)
    dias, horas, z, promedios = dx.mapa_calor(filas)
    info = dx.INFO.get(variable, {})
    return JsonResponse({
        "variable": variable,
        "nombre": info.get("nombre", VARIABLES[variable][0]),
        "unidad": VARIABLES[variable][1],
        "que_es": info.get("que_es", ""),
        "frases": dx.resumen_texto(variable, filas, VARIABLES[variable][1]),
        "escala": list(info.get("palabras_escala", ("Bajo", "Ideal", "Alto"))),
        "mapa": {"dias": [d.strftime("%d/%m") for d in dias], "horas": horas, "z": z, "valores": promedios},
        "desde": timezone.localtime(desde).isoformat(), "hasta": timezone.localtime(hasta).isoformat(),
    })


@login_required
def ayuda(request, sala_id=None):
    sala = _sala(sala_id)
    variables = [(k, dx.INFO[k]) for k in ["vpd", "temperatura", "humedad", "co2", "ph", "ec", "temp_hoja", "temp_solucion"]]
    contexto = _contexto_base(sala) | {"variables": variables, "seccion": "ayuda"}
    return render(request, "cultivo/ayuda.html", contexto)


@login_required
def nuevo_ciclo(request, sala_id):
    """¿Qué estás cultivando? Crea el ciclo con la receta del catálogo."""
    from nucleo.recetas import CATALOGO, FUENTES, duracion_total
    sala = _sala(sala_id)
    if request.method == "POST":
        clave = request.POST.get("cultivo")
        codigo = (request.POST.get("codigo_lote") or "").strip()
        if clave not in CATALOGO or not codigo:
            messages.error(request, "Elegí un cultivo y escribí un nombre para el lote.")
        elif Ciclo.objects.filter(codigo_lote=codigo).exists():
            messages.error(request, f"Ya existe un lote llamado {codigo}.")
        else:
            inicio = timezone.now()
            if request.POST.get("fecha_inicio"):
                inicio = timezone.make_aware(datetime.fromisoformat(request.POST["fecha_inicio"]))
            try:
                etapa_inicial = int(request.POST.get("etapa_inicial", 1))
            except ValueError:
                etapa_inicial = 1
            fert = "organica" if request.POST.get("fertilizacion") == "organica" else "mineral"
            ciclo = servicios.crear_ciclo_desde_catalogo(sala, clave, codigo, inicio, etapa_inicial=etapa_inicial,
                                                         fertilizacion=fert)
            messages.success(request, f"Listo: {sala.nombre} está configurada para {CATALOGO[clave]['nombre'].lower()}. "
                                      "Cuando el cultivo cambie de etapa, avisale al sistema con el botón del panel.")
            return redirect("panel_sala", sala_id=sala.id)
    cultivos = [{
        "clave": k, "nombre": c["nombre"], "descripcion": c["descripcion"], "sistema": c["sistema"],
        "dias": duracion_total(k), "etapas": [e["nombre"] for e in c["etapas"]], "vigila": c.get("vigila", ""),
        "rangos": c["etapas"][-1]["rangos"], "fuentes": [FUENTES[n] for n in c["fuentes"]],
    } for k, c in CATALOGO.items()]
    actual = sala.ciclo_activo()
    clave_actual = actual.receta.cultivo if actual else ""
    elegido = request.GET.get("cultivo") or (clave_actual if clave_actual in CATALOGO else next(iter(CATALOGO)))
    contexto = _contexto_base(sala) | {
        "cultivos": cultivos, "seccion": "recetas", "actual": actual, "clave_actual": clave_actual,
        "elegido": elegido,
        "sugerido": f"L-{timezone.localdate():%Y%m%d}", "hoy": timezone.localdate().isoformat(),
    }
    return render(request, "cultivo/nuevo_ciclo.html", contexto)


@login_required
@require_POST
def pausa(request, sala_id):
    sala = _sala(sala_id)
    sala.control_pausado = not sala.control_pausado
    sala.pausado_desde = timezone.now() if sala.control_pausado else None
    sala.save(update_fields=["control_pausado", "pausado_desde"])
    if sala.control_pausado:
        messages.warning(request, "Control automático en pausa: el sistema sigue midiendo y avisando, "
                                  "pero no prende ni apaga nada hasta que lo reanudes.")
    else:
        messages.success(request, "Control automático reanudado.")
    return redirect("panel_sala", sala_id=sala.id)


@login_required
def api_puntajes(request, sala_id):
    return JsonResponse(servicios.puntajes_sala(_sala(sala_id)))


def _numero(texto):
    return float(str(texto).replace(",", ".").strip())


@login_required
def mi_cultivo(request, sala_id):
    """La receta del cultivo actual, explicada y editable sin entrar a la administración."""
    from nucleo.recetas import CATALOGO
    from .models import RangoObjetivo
    sala = _sala(sala_id)
    ciclo = sala.ciclo_activo()
    if ciclo is None:
        return redirect("nuevo_ciclo", sala_id=sala.id)
    receta = ciclo.receta

    if request.method == "POST" and request.POST.get("accion") == "restaurar" and receta.cultivo in CATALOGO:
        base = CATALOGO[receta.cultivo]["etapas"]
        for etapa in receta.etapas.all():
            if etapa.orden <= len(base):
                datos = base[etapa.orden - 1]
                etapa.rangos.all().delete()
                RangoObjetivo.objects.bulk_create([
                    RangoObjetivo(etapa=etapa, variable=v, minimo=mn, maximo=mx) for v, (mn, mx) in datos["rangos"].items()
                ])
                etapa.avisos = datos.get("avisos", {})
                etapa.save(update_fields=["avisos"])
        messages.success(request, "Se restauraron los valores recomendados del plan.")
        return redirect("mi_cultivo", sala_id=sala.id)

    if request.method == "POST" and request.POST.get("accion") == "guardar":
        errores, cambios = [], 0
        for rango in RangoObjetivo.objects.filter(etapa__receta=receta):
            mn, mx = request.POST.get(f"min-{rango.id}"), request.POST.get(f"max-{rango.id}")
            if mn is None or mx is None:
                continue
            try:
                mn, mx = _numero(mn), _numero(mx)
            except ValueError:
                errores.append(f"{rango.etapa.nombre} · {VARIABLES[rango.variable][0]}: no es un número")
                continue
            if mn >= mx:
                errores.append(f"{rango.etapa.nombre} · {VARIABLES[rango.variable][0]}: el mínimo debe ser menor que el máximo")
                continue
            if (mn, mx) != (rango.minimo, rango.maximo):
                rango.minimo, rango.maximo = mn, mx
                rango.save(update_fields=["minimo", "maximo"])
                cambios += 1
        validada = (request.POST.get("validada_por") or "").strip()
        if validada != receta.validada_por:
            receta.validada_por = validada
            receta.save(update_fields=["validada_por"])
            cambios += 1
        for e in errores:
            messages.error(request, e)
        if cambios:
            messages.success(request, f"Plan actualizado ({cambios} valores cambiados). El control usa los nuevos rangos desde ahora.")
        return redirect("mi_cultivo", sala_id=sala.id)

    orden_vars = ["vpd", "temperatura", "humedad", "co2", "ph", "ec", "temp_solucion"]
    etapa_actual = ciclo.etapa_en()
    etapas = []
    inicios = {}
    for e_, ini, _ in ciclo.ventanas_etapas():
        inicios.setdefault(e_.id, ini)
    for etapa in receta.etapas.all():
        rangos = {r.variable: r for r in etapa.rangos.all()}
        etapas.append({
            "etapa": etapa, "inicio": inicios.get(etapa.id), "actual": etapa_actual and etapa.id == etapa_actual.id,
            "filas": [{"variable": v, "nombre": dx.INFO.get(v, {}).get("nombre", VARIABLES[v][0]),
                       "grupo": "solucion" if v in ("ph", "ec", "temp_solucion") else "clima",
                       "unidad": VARIABLES[v][1], "rango": rangos[v], "aviso": (etapa.avisos or {}).get(v, "")}
                      for v in orden_vars if v in rangos],
        })
    contexto = _contexto_base(sala) | {
        "ciclo": ciclo, "receta": receta, "etapas": etapas, "etapa_actual": etapa_actual,
        "linea": servicios.linea_tiempo(ciclo), "del_catalogo": receta.cultivo in CATALOGO,
        "seccion": "cultivo",
    }
    return render(request, "cultivo/mi_cultivo.html", contexto)


@login_required
def api_horas(request, sala_id):
    """Últimas 24 horas, hora por hora, de las variables de clima."""
    sala = _sala(sala_id)
    ciclo = sala.ciclo_activo()
    hasta = timezone.now()
    desde = hasta - timedelta(hours=24)
    variables = []
    for v in ("vpd", "temperatura", "humedad"):
        filas = servicios.filas_con_rango(sala, ciclo, v, desde, hasta)
        info = dx.INFO[v]
        variables.append({
            "variable": v, "nombre": info["nombre"], "unidad": VARIABLES[v][1],
            "escala": list(info["palabras_escala"]),
            "horas": dx.franjas_horarias(filas, timezone.localtime(hasta)),
        })
    return JsonResponse({"variables": variables})


def novedades(sala, ciclo):
    """Mensajes que rotan en el panel para que el usuario descubra lo que puede hacer."""
    from nucleo.recetas import CATALOGO
    nombres = ", ".join(c["nombre"].split(" ")[0].lower() for c in CATALOGO.values())
    mensajes = []
    comp = servicios.comparacion(sala, ciclo)
    if comp and comp["mejora"] > 0:
        mensajes.append({"texto": f"Desde que el sistema controla, la sequedad del aire está en el rango ideal el {comp['despues']}% del tiempo "
                                  f"(antes, con horario fijo, el {comp['antes']}%).",
                         "accion": "Ver la comparación", "url": reverse("historial", args=[sala.id])})
    if ciclo:
        mensajes.append({"texto": f"Estás cultivando {ciclo.cultivo.lower()}: el sistema usa un plan con los valores ideales de cada etapa.",
                         "accion": "Ver mi plan", "url": reverse("mi_cultivo", args=[sala.id])})
    mensajes += [
        {"texto": f"Tenemos planes de cultivo listos para {nombres}. Elegí el tuyo y el sistema se configura solo.",
         "accion": "Ver planes", "url": reverse("nuevo_ciclo", args=[sala.id])},
        {"texto": "¿Cambiaste de cultivo? Empezá un ciclo nuevo y el sistema adapta todos los rangos.",
         "accion": "Cambiar cultivo", "url": reverse("nuevo_ciclo", args=[sala.id])},
        {"texto": "Podés ajustar cualquier valor de tu plan de cultivo, y volver a los recomendados cuando quieras.",
         "accion": "Ajustar plan", "url": reverse("mi_cultivo", args=[sala.id])},
        {"texto": "¿Necesitás manejar todo a mano? Pausá el sistema: sigue midiendo pero no prende ni apaga nada.",
         "accion": None, "url": None},
        {"texto": "Mirá en qué horarios se te va el clima de rango con el mapa de calor y la nota de cada día.",
         "accion": "Ver historial", "url": reverse("historial", args=[sala.id])},
        {"texto": "Los planes de cultivo se basan en publicaciones del INTA y otras fuentes técnicas. Cada valor tiene su fuente a la vista.",
         "accion": "Ver fuentes", "url": reverse("mi_cultivo", args=[sala.id])},
        {"texto": "Tu ingeniero agrónomo puede revisar el plan, ajustarlo y dejar su firma en el sistema.",
         "accion": "Ver mi plan", "url": reverse("mi_cultivo", args=[sala.id])},
        {"texto": "Vos decidís cuándo el cultivo cambia de etapa: avisale al sistema con un botón y se adapta solo.",
         "accion": None, "url": None},
        {"texto": "Nuestro kit de sensores mide el clima real de tu cultivo cada pocos segundos, y el sistema decide con tu plan de cultivo.",
         "accion": "Conocer el kit", "url": reverse("kit", args=[sala.id])},
        {"texto": "¿No tenés humidificador o calefacción? No pasa nada: el sistema controla lo que tenés y te avisa cuando algo le falta.",
         "accion": "Mis equipos", "url": reverse("equipos", args=[sala.id])},
        {"texto": "Tu cámara saca una foto por día: al final del ciclo tenés el time-lapse completo, de plantín a cosecha.",
         "accion": "Ver time-lapse", "url": reverse("timelapse", args=[ciclo.id]) if ciclo else reverse("camara", args=[sala.id])},
        {"texto": "¿Tenés más de una sala o invernadero? Cada uno puede tener su propio cultivo y su plan.",
         "accion": "Mis salas", "url": reverse("mis_cultivos")},
    ]
    if ciclo and ciclo.receta.validada_por:
        mensajes.insert(0, {"texto": f"Tu plan de {ciclo.cultivo.lower()} fue revisado por {ciclo.receta.validada_por}.",
                            "accion": "Ver plan", "url": reverse("mi_cultivo", args=[sala.id])})
    return mensajes


@login_required
@require_POST
def cambiar_etapa(request, ciclo_id):
    """El productor avisa que el cultivo pasó a otra etapa (o corrige la actual)."""
    from .models import Etapa
    ciclo = get_object_or_404(Ciclo, pk=ciclo_id)
    etapa = get_object_or_404(Etapa, pk=request.POST.get("etapa"), receta=ciclo.receta)
    actual = ciclo.etapa_en()
    if actual and actual.id == etapa.id:
        messages.info(request, f"El cultivo ya está en {etapa.nombre}.")
    else:
        ciclo.cambiar_etapa(etapa, usuario=request.user)
        texto = f"Listo: {ciclo.cultivo} pasó a {etapa.nombre}. El sistema ya usa los valores de esta etapa."
        if actual and etapa.horas_luz != actual.horas_luz:
            texto += f" Recordá ajustar las luces a {etapa.horas_luz} horas."
        messages.success(request, texto)
    destino = request.POST.get("volver")
    if destino == "mi_cultivo":
        return redirect("mi_cultivo", sala_id=ciclo.sala_id)
    return redirect("panel_sala", sala_id=ciclo.sala_id)


@login_required
def mis_cultivos(request):
    """Todas las salas o invernaderos del usuario, cada uno con su cultivo."""
    tarjetas = []
    for sala in Sala.objects.order_by("id"):
        ciclo = sala.ciclo_activo()
        simple = servicios.estado_simple(sala) if ciclo else None
        tarjetas.append({"sala": sala, "ciclo": ciclo, "simple": simple,
                         "etapa": ciclo.etapa_en() if ciclo else None,
                         "linea": servicios.linea_tiempo(ciclo) if ciclo else None})
    sala = Sala.objects.order_by("id").first()
    contexto = {"sala": sala, "salas": Sala.objects.all(), "tarjetas": tarjetas, "seccion": "mis_cultivos"}
    return render(request, "cultivo/mis_cultivos.html", contexto)


@login_required
@require_POST
def nueva_sala(request):
    nombre = (request.POST.get("nombre") or "").strip()
    if not nombre:
        messages.error(request, "Poné un nombre para la sala o invernadero.")
        return redirect("mis_cultivos")
    sala = Sala.objects.create(nombre=nombre)
    messages.success(request, f"Se creó {nombre}. Ahora contale al sistema qué vas a cultivar ahí.")
    return redirect("nuevo_ciclo", sala_id=sala.id)


EQUIPOS_DISPONIBLES = [
    # tipo, nombre, para qué sirve
    ("extractor", "Extractores", "Sacan el aire caliente y húmedo. Es lo más común en invernaderos."),
    ("calefactor", "Calefacción", "Sube la temperatura en noches frías y ayuda a secar el aire."),
    ("humidificador", "Humidificador", "Agrega humedad cuando el aire está seco. Sin él, el sistema solo puede avisar."),
    ("deshumidificador", "Deshumidificador", "Saca humedad sin abrir al exterior; útil con frío o en días de lluvia."),
    ("ventilador", "Ventiladores internos", "Mueven el aire dentro de la sala: evitan bolsones de humedad entre las plantas y emparejan la temperatura."),
    ("luz", "Luces", "Para salas con iluminación artificial: las enciende y apaga según las horas de luz de la etapa."),
    ("riego", "Riego automático", "Opcional. Depende de la bomba, el caudal y si cultivás en maceta, en suelo o en hidroponía (donde la solución circula todo el tiempo); por eso se configura en una sección propia, en desarrollo. Si regás a mano, registrás cada riego con un botón."),
]

# Equipos que se cargan con cantidad (el resto es "lo tengo / no lo tengo")
CANTIDADES = {"extractor": (4, "Extractor"), "ventilador": (20, "Ventilador")}


@login_required
def equipos(request, sala_id):
    """¿Qué equipos tenés? El sistema controla los que hay y avisa por los que faltan."""
    sala = _sala(sala_id)
    if request.method == "POST":
        for tipo, nombre, _ in EQUIPOS_DISPONIBLES:
            existentes = list(sala.actuadores.filter(tipo=tipo).order_by("-activo", "orden"))
            if tipo in CANTIDADES:
                maximo = CANTIDADES[tipo][0]
                try:
                    cantidad = max(0, min(maximo, int(request.POST.get(tipo, 0) or 0)))
                except ValueError:
                    cantidad = sum(1 for a in existentes if a.activo)
            else:
                cantidad = 1 if request.POST.get(tipo) else 0
            # Los equipos que se sacan se desactivan (no se borran) para no perder su historial
            for i, a in enumerate(existentes):
                if a.activo != (i < cantidad):
                    a.activo = i < cantidad
                    a.save(update_fields=["activo", "actualizado"])
            for i in range(len(existentes), cantidad):
                Actuador.objects.create(sala=sala, tipo=tipo, orden=i + 1,
                                        nombre=f"{CANTIDADES[tipo][1]} {i + 1}" if tipo in CANTIDADES else nombre)
        messages.success(request, "Equipos actualizados. Para conectar cada uno a su interruptor (Tuya, Shelly, etc.) "
                                  "cargá los datos de conexión en Administración → Actuadores.")
        return redirect("equipos", sala_id=sala.id)
    actuales = {}
    for tipo in sala.actuadores.filter(activo=True).values_list("tipo", flat=True):
        actuales[tipo] = actuales.get(tipo, 0) + 1
    lista = [{"tipo": t, "nombre": n, "texto": x, "cantidad": actuales.get(t, 0),
              "maximo": CANTIDADES.get(t, (None,))[0]} for t, n, x in EQUIPOS_DISPONIBLES]
    contexto = _contexto_base(sala) | {"lista": lista, "seccion": "equipos",
                                       "camaras": sala.camaras.filter(activa=True),
                                       "simple": servicios.estado_simple(sala)}
    return render(request, "cultivo/equipos.html", contexto)


@login_required
@require_POST
def registrar_solucion(request, sala_id):
    """Medición manual del día de pH y EC (cuando no hay sondas en el tanque)."""
    from .models import EventoBitacora, Lectura
    sala = _sala(sala_id)
    ahora = timezone.now()
    valores = {}
    for clave, minimo, maximo in (("ph", 0, 14), ("ec", 0, 10)):
        texto = (request.POST.get(clave) or "").strip()
        if not texto:
            continue
        try:
            valor = _numero(texto)
        except ValueError:
            messages.error(request, f"El valor de {clave.upper()} no es un número.")
            return redirect("panel_sala", sala_id=sala.id)
        if not minimo <= valor <= maximo:
            messages.error(request, f"El {clave.upper()} tiene que estar entre {minimo} y {maximo}.")
            return redirect("panel_sala", sala_id=sala.id)
        valores[clave] = valor
    if not valores:
        messages.error(request, "Cargá al menos el pH o la EC.")
        return redirect("panel_sala", sala_id=sala.id)
    Lectura.objects.bulk_create([Lectura(sala=sala, variable=k, valor=v, momento=ahora, origen="manual")
                                 for k, v in valores.items()])
    ciclo = sala.ciclo_activo()
    if ciclo:
        EventoBitacora.objects.create(ciclo=ciclo, momento=ahora, tipo="medicion", usuario=request.user,
                                      ph=valores.get("ph"), ec=valores.get("ec"),
                                      descripcion="Medición manual del día desde el panel.")
    messages.success(request, "Medición guardada. ¡Gracias! Mañana te lo vuelvo a recordar.")
    return redirect("panel_sala", sala_id=sala.id)


@login_required
def kit(request, sala_id=None):
    sala = _sala(sala_id)
    contexto = _contexto_base(sala) | {"seccion": "kit"}
    return render(request, "cultivo/kit.html", contexto)


# ------------------------------------------------------------------ Cámaras

@login_required
def camara(request, sala_id):
    """Cámaras en vivo de la sala y alta de cámaras nuevas."""
    sala = _sala(sala_id)
    form = CamaraForm(request.POST or None, initial={"nombre": f"Cámara {sala.camaras.count() + 1}"})
    if request.method == "POST" and form.is_valid():
        nueva = form.save(commit=False)
        nueva.sala = sala
        nueva.orden = sala.camaras.count() + 1
        nueva.save()
        messages.success(request, f"Cámara «{nueva.nombre}» agregada.")
        return redirect("camara", sala_id=sala.id)
    ciclo = sala.ciclo_activo()
    fotos = ciclo.eventos.exclude(foto="").order_by("-momento")[:12] if ciclo else []
    contexto = _contexto_base(sala) | {"camaras": sala.camaras.filter(activa=True), "form": form,
                                       "ciclo": ciclo, "fotos": fotos, "seccion": "camara"}
    return render(request, "cultivo/camara.html", contexto)


@login_required
@require_POST
def camara_quitar(request, pk):
    cam = get_object_or_404(Camara, pk=pk)
    cam.activa = False
    cam.save(update_fields=["activa"])
    messages.success(request, f"Se quitó la cámara «{cam.nombre}».")
    return redirect("camara", sala_id=cam.sala_id)


@login_required
@require_POST
def camara_foto(request, pk):
    """Saca una foto con la cámara y la guarda en la bitácora del ciclo."""
    from nucleo.camara import ErrorCamara, capturar
    from .models import EventoBitacora
    cam = get_object_or_404(Camara, pk=pk)
    destino = request.POST.get("volver") or reverse("camara", args=[cam.sala_id])
    if not destino.startswith("/"):
        destino = reverse("camara", args=[cam.sala_id])
    ciclo = cam.sala.ciclo_activo()
    if not ciclo:
        messages.error(request, "Para guardar fotos primero elegí qué estás cultivando.")
        return redirect(destino)
    if cam.es_demo:
        messages.info(request, "La cámara de demostración no guarda fotos. Conectá una cámara real o subí una foto desde la bitácora.")
        return redirect(destino)
    try:
        datos = capturar(cam.url_foto or cam.url)
    except ErrorCamara as e:
        messages.error(request, str(e))
        return redirect(destino)
    ahora = timezone.localtime()
    evento = EventoBitacora(ciclo=ciclo, momento=ahora, tipo="foto", usuario=request.user,
                            descripcion=(request.POST.get("nota") or "").strip() or f"Foto de {cam.nombre}.")
    evento.foto.save(f"{cam.sala_id}-{ahora:%Y%m%d-%H%M%S}.jpg", ContentFile(datos), save=False)
    evento.save()
    messages.success(request, "Foto guardada en la bitácora.")
    return redirect(destino)


@login_required
def camara_demo(request, sala_id):
    """Imagen de demostración (SVG) para mostrar la cámara sin hardware."""
    from .fotos import crecimiento_del_ciclo, svg_demo
    sala = _sala(sala_id)
    ciclo = sala.ciclo_activo()
    ahora = timezone.now()
    crecimiento = crecimiento_del_ciclo(ciclo, ahora) if ciclo else 0.5
    respuesta = HttpResponse(svg_demo(sala.nombre, timezone.localtime(ahora), crecimiento), content_type="image/svg+xml")
    respuesta["Cache-Control"] = "no-store"
    return respuesta


@login_required
def timelapse(request, ciclo_id):
    """Una foto por día del ciclo, de principio a fin, con reproductor de time-lapse."""
    ciclo = get_object_or_404(Ciclo, pk=ciclo_id)
    fotos = list(ciclo.fotos_diarias.select_related("camara"))
    camaras = sorted({f.camara for f in fotos if f.camara}, key=lambda c: c.orden)
    elegida = request.GET.get("camara")
    if elegida:
        fotos = [f for f in fotos if str(f.camara_id) == elegida]
    elif camaras:
        fotos = [f for f in fotos if f.camara_id == camaras[0].id]
    cuadros = []
    for f in fotos:
        etapa = ciclo.etapa_en(f.momento)
        cuadros.append({"url": f.archivo.url, "dia": ciclo.dia(f.momento), "fecha": f.fecha.strftime("%d/%m/%Y"),
                        "etapa": etapa.nombre if etapa else ""})
    camara_activa = ciclo.sala.camaras.filter(activa=True, foto_diaria=True).first()
    contexto = _contexto_base(ciclo.sala) | {
        "ciclo": ciclo, "cuadros": cuadros, "camaras": camaras, "seccion": "ciclos",
        "camara_elegida": int(elegida) if elegida and elegida.isdigit() else (camaras[0].id if camaras else None),
        "camara_activa": camara_activa,
    }
    return render(request, "cultivo/timelapse.html", contexto)
