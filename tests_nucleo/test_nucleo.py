"""Pruebas del núcleo. Ejecutar con: python -m unittest discover tests_nucleo"""
import unittest
from datetime import datetime, timedelta

from nucleo.vpd import presion_saturacion, vpd_aire, vpd_hoja, humedad_absoluta, hr_desde_humedad_absoluta
from nucleo.reglas import Rango, decidir_extraccion, decidir_calefaccion, nivel_a_extractores
from nucleo.controlador import ControladorClima
from nucleo.drivers import crear_driver, ErrorDriver
from nucleo.simulacion import ModeloInvernadero, ClimaExterior, luces_encendidas, extractores_por_horario

VPD_VEG = Rango(0.8, 1.2)
TEMP_VEG = Rango(20, 28)


class TestVPD(unittest.TestCase):
    def test_presion_saturacion_valores_de_referencia(self):
        self.assertAlmostEqual(presion_saturacion(20), 2.339, places=2)
        self.assertAlmostEqual(presion_saturacion(26), 3.361, places=2)

    def test_ejemplo_de_la_ficha(self):
        self.assertAlmostEqual(vpd_aire(26, 60), 1.34, places=2)
        self.assertAlmostEqual(vpd_hoja(26, 60, 24), 0.97, places=2)

    def test_vpd_hoja_sin_temp_hoja_igual_a_aire(self):
        self.assertAlmostEqual(vpd_hoja(25, 55), vpd_aire(25, 55), places=6)

    def test_humedad_absoluta_ida_y_vuelta(self):
        ah = humedad_absoluta(24, 65)
        self.assertAlmostEqual(hr_desde_humedad_absoluta(24, ah), 65, places=6)


class TestReglas(unittest.TestCase):
    def test_dentro_de_rango_no_extrae(self):
        d = decidir_extraccion(1.0, 24, VPD_VEG, TEMP_VEG, 0, 60)
        self.assertEqual(d.nivel, 0)

    def test_vpd_bajo_un_extractor(self):
        d = decidir_extraccion(0.75, 24, VPD_VEG, TEMP_VEG, 0, 60)
        self.assertEqual(d.nivel, 1)

    def test_vpd_muy_bajo_ambos(self):
        d = decidir_extraccion(0.5, 24, VPD_VEG, TEMP_VEG, 0, 60)
        self.assertEqual(d.nivel, 2)

    def test_anticiclado(self):
        d = decidir_extraccion(0.5, 24, VPD_VEG, TEMP_VEG, 0, 2)
        self.assertEqual(d.nivel, 0)

    def test_emergencia_termica_ignora_anticiclado(self):
        d = decidir_extraccion(1.0, 31, VPD_VEG, TEMP_VEG, 0, 1)
        self.assertEqual(d.nivel, 2)

    def test_histeresis_mantiene_hasta_el_centro(self):
        d = decidir_extraccion(0.9, 24, VPD_VEG, TEMP_VEG, 1, 60)
        self.assertEqual(d.nivel, 1)
        d = decidir_extraccion(1.05, 24, VPD_VEG, TEMP_VEG, 1, 60)
        self.assertEqual(d.nivel, 0)

    def test_no_extrae_si_afuera_esta_mas_humedo(self):
        d = decidir_extraccion(0.6, 24, VPD_VEG, TEMP_VEG, 0, 60, ah_interior=12, ah_exterior=14)
        self.assertEqual(d.nivel, 0)

    def test_no_extrae_con_frio(self):
        d = decidir_extraccion(0.5, 18, VPD_VEG, TEMP_VEG, 0, 60)
        self.assertEqual(d.nivel, 0)

    def test_calefactor_con_frio_y_para_deshumidificar(self):
        self.assertEqual(decidir_calefaccion(1.0, 20.5, VPD_VEG, TEMP_VEG, False).nivel, 1)
        self.assertEqual(decidir_calefaccion(0.6, 22, VPD_VEG, TEMP_VEG, False).nivel, 1)
        self.assertEqual(decidir_calefaccion(1.0, 27.5, VPD_VEG, TEMP_VEG, True).nivel, 0)

    def test_nivel_a_extractores_escalonado(self):
        self.assertEqual(nivel_a_extractores(1, 2), [True, False])
        self.assertEqual(nivel_a_extractores(2, 2), [True, True])


class TestDrivers(unittest.TestCase):
    def test_driver_simulado(self):
        d = crear_driver("simulado")
        d.encender()
        self.assertTrue(d.estado())
        d.aplicar(False)
        self.assertFalse(d.estado())

    def test_driver_desconocido(self):
        with self.assertRaises(ErrorDriver):
            crear_driver("marca_inexistente")


class TestSimulacion(unittest.TestCase):
    def _correr(self, lazo_cerrado: bool) -> float:
        modelo, clima, ctl = ModeloInvernadero(), ClimaExterior(), ControladorClima()
        t = datetime(2026, 9, 20)
        dentro = total = 0
        n, cal = 0, False
        for _ in range(288 * 7):
            te, he = clima.en(t)
            if not lazo_cerrado:
                n = extractores_por_horario(t)
            l = modelo.paso(5, n, luces_encendidas(t, 18), te, he, cal)
            if lazo_cerrado:
                s = ctl.evaluar(l["temperatura"], l["humedad"], l["vpd"], VPD_VEG, TEMP_VEG, 5, te, he)
                n, cal = s.nivel_extraccion, s.calefactor
            dentro += VPD_VEG.contiene(l["vpd"])
            total += 1
            t += timedelta(minutes=5)
        return dentro / total

    def test_lecturas_en_rangos_fisicos(self):
        modelo = ModeloInvernadero()
        for _ in range(500):
            l = modelo.paso(5, 1, True, 18, 70)
            self.assertTrue(0 <= l["humedad"] <= 100)
            self.assertTrue(-5 < l["temperatura"] < 50)

    def test_lazo_cerrado_mejora_tiempo_en_rango(self):
        self.assertGreater(self._correr(True), self._correr(False))


if __name__ == "__main__":
    unittest.main()


class TestHumedad(unittest.TestCase):
    def test_humidificador_y_deshumidificador(self):
        from nucleo.reglas import decidir_humidificacion, decidir_deshumidificacion
        hr = Rango(60, 80)
        self.assertEqual(decidir_humidificacion(1.5, 50, VPD_VEG, hr, False).nivel, 1)
        self.assertEqual(decidir_humidificacion(1.0, 70, VPD_VEG, hr, False).nivel, 0)
        self.assertEqual(decidir_humidificacion(1.1, 65, VPD_VEG, hr, True).nivel, 1)  # histéresis
        self.assertEqual(decidir_deshumidificacion(0.5, 85, VPD_VEG, hr, False).nivel, 1)
        self.assertEqual(decidir_deshumidificacion(1.5, 50, VPD_VEG, hr, True).nivel, 0)

    def test_controlador_solo_usa_lo_que_hay(self):
        ctl = ControladorClima()
        s = ctl.evaluar(24, 40, 1.8, VPD_VEG, TEMP_VEG, 10, rango_hr=Rango(60, 80))
        self.assertFalse(s.humidificador)
        s = ctl.evaluar(24, 40, 1.8, VPD_VEG, TEMP_VEG, 10, rango_hr=Rango(60, 80), tiene_humidificador=True)
        self.assertTrue(s.humidificador)


class CamaraTest(unittest.TestCase):
    JPEG = b"\xff\xd8" + b"datos de la imagen" + b"\xff\xd9"

    def test_extrae_foto_suelta(self):
        from nucleo.camara import extraer_cuadro
        self.assertEqual(extraer_cuadro(self.JPEG), self.JPEG)
        self.assertIsNone(extraer_cuadro(b"<html>error</html>"))

    def test_extrae_primer_cuadro_de_un_flujo_mjpeg(self):
        import io
        from nucleo.camara import capturar
        flujo = (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + self.JPEG
                 + b"\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\n" + b"\xff\xd8otro")
        cuadro = capturar("http://camara/stream", abrir=lambda url, timeout: io.BytesIO(flujo))
        self.assertEqual(cuadro, self.JPEG)

    def test_errores_claros(self):
        import io
        from nucleo.camara import ErrorCamara, capturar
        with self.assertRaises(ErrorCamara):
            capturar("ftp://camara")
        with self.assertRaises(ErrorCamara):
            capturar("http://camara", abrir=lambda url, timeout: io.BytesIO(b"no es una imagen"))

        def caida(url, timeout):
            raise OSError("sin conexión")
        with self.assertRaises(ErrorCamara):
            capturar("http://camara", abrir=caida)
