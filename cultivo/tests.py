"""Pruebas de la app web. Ejecutar con: python manage.py test"""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import AccionActuador, Actuador, Ciclo, Lectura, Sala
from .servicios import estado_variable


class EstadoVariableTest(TestCase):
    def test_estados(self):
        self.assertEqual(estado_variable(1.0, (0.8, 1.2)), "ok")
        self.assertEqual(estado_variable(0.75, (0.8, 1.2)), "atencion")
        self.assertEqual(estado_variable(0.3, (0.8, 1.2)), "fuera")
        self.assertEqual(estado_variable(1.0, None), "sin-rango")


class DemoYVistasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("simular", reset=True, dias=3, cambio=1, verbosity=0)
        cls.sala = Sala.objects.get(nombre="Sala demo")

    def setUp(self):
        self.client.force_login(get_user_model().objects.get(username="demo"))

    def test_demo_genera_datos(self):
        self.assertGreater(Lectura.objects.filter(sala=self.sala, variable="vpd").count(), 800)
        self.assertTrue(Ciclo.objects.filter(sala=self.sala).exists())
        self.assertEqual(self.sala.periodos.count(), 2)

    def test_paginas_responden(self):
        ciclo = self.sala.ciclo_activo()
        for url in [
            reverse("panel"), reverse("panel_sala", args=[self.sala.id]),
            reverse("historial", args=[self.sala.id]), reverse("ciclos", args=[self.sala.id]),
            reverse("experimento", args=[self.sala.id]), reverse("ciclo_detalle", args=[ciclo.id]),
            reverse("bitacora_nuevo", args=[ciclo.id]), reverse("ayuda", args=[self.sala.id]),
            reverse("nuevo_ciclo", args=[self.sala.id]), reverse("mi_cultivo", args=[self.sala.id]),
            reverse("mis_cultivos"), reverse("equipos", args=[self.sala.id]), reverse("kit", args=[self.sala.id]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_apis(self):
        r = self.client.get(reverse("api_estado", args=[self.sala.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["tarjetas"]), 8)
        r = self.client.get(reverse("api_serie", args=[self.sala.id]), {"horas": 24, "variables": "vpd,temperatura"})
        self.assertIn("vpd", r.json()["series"])
        r = self.client.get(reverse("api_experimento", args=[self.sala.id]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("diagnostico", self.client.get(reverse("api_estado", args=[self.sala.id])).json())
        for dias in ("1", "7", "ciclo"):
            r = self.client.get(reverse("api_resumen", args=[self.sala.id]), {"variable": "vpd", "dias": dias})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["frases"])

    def test_accion_rapida_ventilar_y_volver_a_auto(self):
        self.client.post(reverse("accion_rapida", args=[self.sala.id]), {"accion": "ventilar"})
        for e in Actuador.objects.filter(sala=self.sala, tipo="extractor"):
            self.assertEqual((e.modo, e.encendido), ("manual", True))
            self.assertIsNotNone(e.manual_hasta)
        self.client.post(reverse("accion_rapida", args=[self.sala.id]), {"accion": "auto"})
        self.assertFalse(Actuador.objects.filter(sala=self.sala, modo="manual").exists())

    def test_comando_manual_registra_accion(self):
        extractor = Actuador.objects.filter(sala=self.sala, tipo="extractor").first()
        self.client.post(reverse("actuador_comando", args=[extractor.id]), {"comando": "encender"})
        extractor.refresh_from_db()
        self.assertEqual(extractor.modo, "manual")
        self.assertTrue(extractor.encendido)
        self.assertTrue(AccionActuador.objects.filter(actuador=extractor, origen="manual").exists())

    def test_requiere_login(self):
        self.client.logout()
        r = self.client.get(reverse("panel"))
        self.assertEqual(r.status_code, 302)

    def test_nuevo_ciclo_desde_catalogo(self):
        r = self.client.post(reverse("nuevo_ciclo", args=[self.sala.id]),
                             {"cultivo": "lechuga", "codigo_lote": "L-TEST", "fecha_inicio": "2026-10-01"})
        self.assertEqual(r.status_code, 302)
        ciclo = Ciclo.objects.get(codigo_lote="L-TEST")
        self.assertEqual(ciclo.receta.cultivo, "lechuga")
        self.assertEqual(ciclo.receta.etapas.count(), 2)
        self.assertEqual(self.sala.ciclo_activo(), ciclo)
        self.assertIsNotNone(Ciclo.objects.get(codigo_lote="DEMO-001").fecha_fin)

    def test_pausa(self):
        self.client.post(reverse("pausa", args=[self.sala.id]))
        self.sala.refresh_from_db()
        self.assertTrue(self.sala.control_pausado)
        self.assertIn("pausa", self.client.get(reverse("api_estado", args=[self.sala.id])).json()["diagnostico"]["resumen"])
        self.client.post(reverse("pausa", args=[self.sala.id]))
        self.sala.refresh_from_db()
        self.assertFalse(self.sala.control_pausado)

    def test_puntajes(self):
        d = self.client.get(reverse("api_puntajes", args=[self.sala.id])).json()
        self.assertTrue(d["dias"])
        self.assertIn("semana", d)

    def test_mi_cultivo_editar_y_restaurar(self):
        from .models import RangoObjetivo
        rango = RangoObjetivo.objects.filter(etapa__receta=self.sala.ciclo_activo().receta, variable="vpd").first()
        url = reverse("mi_cultivo", args=[self.sala.id])
        self.client.post(url, {"accion": "guardar", f"min-{rango.id}": "0,6", f"max-{rango.id}": "1,1"})
        rango.refresh_from_db()
        self.assertEqual((rango.minimo, rango.maximo), (0.6, 1.1))
        self.client.post(url, {"accion": "guardar", f"min-{rango.id}": "2", f"max-{rango.id}": "1"})
        rango.refresh_from_db()
        self.assertEqual(rango.minimo, 0.6)  # mínimo mayor que máximo: no se guarda
        self.client.post(url, {"accion": "restaurar"})
        nuevo = RangoObjetivo.objects.get(etapa=rango.etapa, variable="vpd")
        self.assertEqual((nuevo.minimo, nuevo.maximo), (0.5, 0.9))

    def test_api_horas(self):
        d = self.client.get(reverse("api_horas", args=[self.sala.id])).json()
        self.assertEqual(len(d["variables"]), 3)
        self.assertEqual(len(d["variables"][0]["horas"]), 24)

    def test_etapas_las_decide_el_productor(self):
        ciclo = self.sala.ciclo_activo()
        self.assertEqual(ciclo.etapa_en().orden, 1)
        siguiente = ciclo.etapa_siguiente()
        self.client.post(reverse("cambiar_etapa", args=[ciclo.id]), {"etapa": siguiente.id})
        self.assertEqual(ciclo.etapa_en().id, siguiente.id)
        # volver atrás también se puede
        primera = ciclo.receta.etapas.get(orden=1)
        self.client.post(reverse("cambiar_etapa", args=[ciclo.id]), {"etapa": primera.id})
        self.assertEqual(ciclo.etapa_en().id, primera.id)
        self.assertEqual(self.client.get(reverse("ciclo_detalle", args=[ciclo.id])).status_code, 200)

    def test_etapa_inicial_al_crear(self):
        self.client.post(reverse("nuevo_ciclo", args=[self.sala.id]),
                         {"cultivo": "tomate", "codigo_lote": "T-2", "etapa_inicial": "3"})
        ciclo = Ciclo.objects.get(codigo_lote="T-2")
        self.assertEqual(ciclo.etapa_en().orden, 3)

    def test_varias_salas(self):
        r = self.client.post(reverse("nueva_sala"), {"nombre": "Invernadero 2"})
        nueva = Sala.objects.get(nombre="Invernadero 2")
        self.assertRedirects(r, reverse("nuevo_ciclo", args=[nueva.id]))
        self.client.post(reverse("nuevo_ciclo", args=[nueva.id]), {"cultivo": "albahaca", "codigo_lote": "A-1"})
        self.assertEqual(nueva.ciclo_activo().receta.cultivo, "albahaca")
        self.assertEqual(self.sala.ciclo_activo().codigo_lote, "DEMO-001")  # la otra sala no cambia
        self.assertContains(self.client.get(reverse("mis_cultivos")), "Albahaca")

    def test_equipos_se_activan_y_desactivan_sin_perder_historial(self):
        url = reverse("equipos", args=[self.sala.id])
        self.client.post(url, {"extractor": "1", "calefactor": "on", "humidificador": "on", "luz": "on"})
        activos = set(self.sala.actuadores.filter(activo=True).values_list("tipo", flat=True))
        self.assertIn("humidificador", activos)
        self.assertEqual(self.sala.actuadores.filter(activo=True, tipo="extractor").count(), 1)
        self.assertEqual(self.sala.actuadores.filter(tipo="extractor").count(), 2)  # el otro quedó inactivo

    def test_medicion_manual_de_ph_y_ec(self):
        from .models import EventoBitacora, Lectura
        self.client.post(reverse("registrar_solucion", args=[self.sala.id]), {"ph": "6,1", "ec": "1,9"})
        self.assertTrue(Lectura.objects.filter(sala=self.sala, origen="manual", variable="ph", valor=6.1).exists())
        self.assertTrue(EventoBitacora.objects.filter(tipo="medicion", ec=1.9).exists())
        self.client.post(reverse("registrar_solucion", args=[self.sala.id]), {"ph": "20"})
        self.assertFalse(Lectura.objects.filter(sala=self.sala, variable="ph", valor=20).exists())

    def test_cultivo_organico_no_controla_ph_ni_ec(self):
        self.client.post(reverse("nuevo_ciclo", args=[self.sala.id]),
                         {"cultivo": "tomate", "codigo_lote": "ORG-1", "fertilizacion": "organica"})
        ciclo = self.sala.ciclo_activo()
        self.assertEqual(ciclo.fertilizacion, "organica")
        tarjetas = {t["variable"]: t for t in self.client.get(reverse("api_estado", args=[self.sala.id])).json()["tarjetas"]}
        self.assertIsNone(tarjetas["ph"]["minimo"])
        self.assertIsNotNone(tarjetas["vpd"]["minimo"])


class VentiladoresYCamarasTest(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.usuario = get_user_model().objects.create_user("prueba", password="clave-prueba-123")
        self.client.force_login(self.usuario)
        self.sala = Sala.objects.create(nombre="Sala prueba")
        self.client.post(reverse("nuevo_ciclo", args=[self.sala.id]), {"cultivo": "tomate", "codigo_lote": "CAM-1"})

    def test_ventiladores_con_cantidad(self):
        url = reverse("equipos", args=[self.sala.id])
        self.client.post(url, {"extractor": "2", "ventilador": "5"})
        self.assertEqual(self.sala.actuadores.filter(activo=True, tipo="ventilador").count(), 5)
        self.client.post(url, {"extractor": "2", "ventilador": "3"})
        self.assertEqual(self.sala.actuadores.filter(activo=True, tipo="ventilador").count(), 3)
        self.assertTrue(self.sala.actuadores.filter(nombre="Ventilador 5", activo=False).exists())

    def test_agregar_camara_y_verla_en_el_panel(self):
        from .models import Camara
        r = self.client.post(reverse("camara", args=[self.sala.id]),
                             {"nombre": "Cámara 1", "tipo": "video", "url": "http://192.168.0.50:81/stream",
                              "url_foto": "", "intervalo_seg": "10"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Camara.objects.filter(sala=self.sala, url__endswith="/stream").exists())
        self.assertContains(self.client.get(reverse("panel_sala", args=[self.sala.id])), "192.168.0.50:81/stream")
        r = self.client.post(reverse("camara", args=[self.sala.id]),
                             {"nombre": "Mala", "tipo": "video", "url": "javascript:alert(1)", "intervalo_seg": "10"})
        self.assertEqual(r.status_code, 200)  # formulario con error, no se guarda
        self.assertFalse(Camara.objects.filter(nombre="Mala").exists())

    def test_imagen_de_demostracion(self):
        r = self.client.get(reverse("camara_demo", args=[self.sala.id]))
        self.assertEqual(r["Content-Type"], "image/svg+xml")

    def test_sacar_foto_la_guarda_en_la_bitacora(self):
        import shutil
        import tempfile
        from unittest import mock
        from django.test import override_settings
        from .models import Camara, EventoBitacora
        cam = Camara.objects.create(sala=self.sala, nombre="Cámara 1", url="http://camara/stream")
        carpeta = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=carpeta), \
                    mock.patch("nucleo.camara.capturar", return_value=b"\xff\xd8foto\xff\xd9"):
                self.client.post(reverse("camara_foto", args=[cam.id]))
            evento = EventoBitacora.objects.get(tipo="foto")
            self.assertTrue(evento.foto.name.endswith(".jpg"))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)


class TimelapseTest(TestCase):
    def setUp(self):
        import tempfile
        from django.test import override_settings
        self.carpeta = tempfile.mkdtemp()
        self.media = override_settings(MEDIA_ROOT=self.carpeta)
        self.media.enable()
        self.usuario = get_user_model().objects.create_user("prueba", password="clave-prueba-123")
        self.client.force_login(self.usuario)
        self.sala = Sala.objects.create(nombre="Sala prueba")
        self.client.post(reverse("nuevo_ciclo", args=[self.sala.id]), {"cultivo": "tomate", "codigo_lote": "TL-1"})
        self.ciclo = self.sala.ciclo_activo()

    def tearDown(self):
        import shutil
        self.media.disable()
        shutil.rmtree(self.carpeta, ignore_errors=True)

    def test_una_foto_por_dia_y_no_antes_de_la_hora(self):
        from datetime import datetime
        from unittest import mock
        from django.utils import timezone
        from .fotos import sacar_fotos_diarias
        from .models import Camara, FotoDiaria
        Camara.objects.create(sala=self.sala, nombre="Cámara 1", url="http://camara/stream", hora_foto=12)
        tz = timezone.get_current_timezone()
        with mock.patch("nucleo.camara.capturar", return_value=b"\xff\xd8foto\xff\xd9"):
            temprano = timezone.make_aware(datetime.now().replace(hour=9, minute=0), tz)
            self.assertEqual(sacar_fotos_diarias(temprano)[0], [])
            mediodia = temprano.replace(hour=12, minute=5)
            self.assertEqual(len(sacar_fotos_diarias(mediodia)[0]), 1)
            self.assertEqual(sacar_fotos_diarias(mediodia.replace(hour=15))[0], [])  # ya tiene la de hoy
        self.assertEqual(FotoDiaria.objects.filter(ciclo=self.ciclo).count(), 1)

    def test_camara_caida_no_frena_el_sistema(self):
        from datetime import datetime
        from django.utils import timezone
        from .fotos import sacar_fotos_diarias
        from .models import Camara
        Camara.objects.create(sala=self.sala, nombre="Caída", url="http://127.0.0.1:9/stream", hora_foto=0)
        sacadas, errores = sacar_fotos_diarias(timezone.make_aware(datetime.now().replace(hour=12)))
        self.assertEqual(sacadas, [])
        self.assertEqual(len(errores), 1)

    def test_pagina_de_timelapse(self):
        from .fotos import guardar_foto_diaria, svg_demo
        from .models import Camara
        from django.utils import timezone
        from datetime import timedelta
        cam = Camara.objects.create(sala=self.sala, nombre="Demo", url="/demo", tipo="foto")
        url = reverse("timelapse", args=[self.ciclo.id])
        self.assertContains(self.client.get(url), "Todavía no hay fotos")
        for d in range(3):
            momento = self.ciclo.fecha_inicio + timedelta(days=d)
            guardar_foto_diaria(cam, self.ciclo, momento, svg_demo("Sala", timezone.localtime(momento), d / 3).encode(), "svg")
        r = self.client.get(url)
        self.assertContains(r, "Descargar video")
        self.assertContains(r, "Día 3")


class MenuYComparacionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("simular", "--reset", "--dias", "4", "--cambio", "2", verbosity=0)

    def setUp(self):
        self.client.force_login(get_user_model().objects.get(username="demo"))
        self.sala = Sala.objects.get(nombre="Sala demo")

    def test_historial_muestra_lo_que_cambio_con_el_sistema(self):
        r = self.client.get(reverse("historial", args=[self.sala.id]))
        self.assertContains(r, "Lo que cambió con el sistema")
        self.assertNotContains(r, ">Antes y después</a>")  # ya no está en el menú
