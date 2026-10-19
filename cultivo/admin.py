from django.contrib import admin

from .models import (
    AccionActuador, Actuador, Alerta, Camara, Ciclo, FotoDiaria, Cosecha, Etapa, EventoBitacora,
    Lectura, PeriodoExperimento, RangoObjetivo, Receta, Sala,
)


class RangoInline(admin.TabularInline):
    model = RangoObjetivo
    extra = 0


@admin.register(Etapa)
class EtapaAdmin(admin.ModelAdmin):
    list_display = ("receta", "orden", "nombre", "duracion_dias", "horas_luz")
    inlines = [RangoInline]


class EtapaInline(admin.TabularInline):
    model = Etapa
    extra = 0
    show_change_link = True


@admin.register(Receta)
class RecetaAdmin(admin.ModelAdmin):
    inlines = [EtapaInline]


@admin.register(Ciclo)
class CicloAdmin(admin.ModelAdmin):
    list_display = ("codigo_lote", "cultivo", "sala", "receta", "fecha_inicio", "fecha_fin")
    list_filter = ("sala",)


@admin.register(Lectura)
class LecturaAdmin(admin.ModelAdmin):
    list_display = ("momento", "sala", "variable", "valor", "origen")
    list_filter = ("sala", "variable", "origen")
    date_hierarchy = "momento"


@admin.register(Actuador)
class ActuadorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "sala", "tipo", "driver", "orden", "modo", "encendido")
    list_filter = ("sala", "tipo", "driver")


@admin.register(AccionActuador)
class AccionAdmin(admin.ModelAdmin):
    list_display = ("momento", "actuador", "encendido", "origen", "motivo")
    list_filter = ("origen", "actuador")
    date_hierarchy = "momento"


@admin.register(Alerta)
class AlertaAdmin(admin.ModelAdmin):
    list_display = ("momento", "sala", "nivel", "variable", "mensaje", "resuelta")
    list_filter = ("nivel", "resuelta")


@admin.register(EventoBitacora)
class EventoAdmin(admin.ModelAdmin):
    list_display = ("momento", "ciclo", "tipo", "ph", "ec", "descripcion")
    list_filter = ("tipo", "ciclo")


admin.site.register(Sala)
from .models import TransicionEtapa  # noqa: E402
admin.site.register(TransicionEtapa)
admin.site.register(PeriodoExperimento)
admin.site.register(Cosecha)


@admin.register(Camara)
class CamaraAdmin(admin.ModelAdmin):
    list_display = ("nombre", "sala", "tipo", "url", "activa")
    list_filter = ("sala", "activa")


@admin.register(FotoDiaria)
class FotoDiariaAdmin(admin.ModelAdmin):
    list_display = ("ciclo", "fecha", "camara")
    list_filter = ("ciclo",)
