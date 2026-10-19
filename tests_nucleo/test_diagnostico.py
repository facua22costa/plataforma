import unittest
from datetime import datetime, timedelta

from nucleo.diagnostico import (
    explicar, diagnostico_general, puntaje, calificar, desvio_normalizado,
    mapa_calor, resumen_texto, frase_accion,
)


class TestDiagnostico(unittest.TestCase):
    def test_explicar_niveles(self):
        self.assertEqual(explicar("vpd", 1.0, (0.8, 1.2)).etiqueta, "Ideal")
        e = explicar("vpd", 0.75, (0.8, 1.2))
        self.assertEqual((e.nivel, e.lado, e.titulo), ("atencion", "bajo", "Aire muy húmedo"))
        self.assertEqual(explicar("vpd", 1.6, (0.8, 1.2)).nivel, "problema")
        self.assertEqual(explicar("vpd", None, (0.8, 1.2)).nivel, "sin-dato")
        self.assertEqual(explicar("luz", 40000, None).nivel, "ok")

    def test_diagnostico_prioriza_lo_grave(self):
        es = [explicar("ph", 6.4, (5.8, 6.3)), explicar("vpd", 0.4, (0.8, 1.2))]
        d = diagnostico_general(es)
        self.assertEqual(d.estado, "problema")
        self.assertEqual(d.titulo, "Aire muy húmedo")
        self.assertIn("1 variable más", d.resumen)

    def test_todo_en_orden(self):
        self.assertEqual(diagnostico_general([explicar("vpd", 1.0, (0.8, 1.2))]).titulo, "Todo en orden")

    def test_puntaje(self):
        self.assertEqual(puntaje([80, 60, None]), 70)
        self.assertIsNone(puntaje([None]))
        self.assertEqual(calificar(85), "Muy bueno")
        self.assertEqual(calificar(30), "Malo")

    def test_desvio(self):
        self.assertEqual(desvio_normalizado(1.0, (0.8, 1.2)), 0)
        self.assertAlmostEqual(desvio_normalizado(0.6, (0.8, 1.2)), -0.5)
        self.assertEqual(desvio_normalizado(5, (0.8, 1.2)), 1.0)

    def test_mapa_y_resumen(self):
        t0 = datetime(2026, 10, 1)
        filas = []
        for i in range(48 * 12):
            m = t0 + timedelta(minutes=5 * i)
            v = 1.5 if 13 <= m.hour < 17 else 1.0
            filas.append((m, v, (0.8, 1.2)))
        dias, horas, z, prom = mapa_calor(filas)
        self.assertEqual(len(dias), 2)
        self.assertEqual(len(z[0]), 24)
        self.assertGreater(z[0][14], 0)
        self.assertEqual(z[0][3], 0)
        frases = resumen_texto("vpd", filas, "kPa")
        self.assertIn("83%", frases[0])
        self.assertIn("aire muy seco", frases[1])
        self.assertIn("de 13 a 17 h", frases[2])

    def test_frase_accion(self):
        self.assertEqual(frase_accion("Extractor 1", True, "aire húmedo"), "Extractor 1 se encendió: aire húmedo")


if __name__ == "__main__":
    unittest.main()


class TestPuntajesYRecetas(unittest.TestCase):
    def test_puntajes_diarios(self):
        from nucleo.diagnostico import puntajes_diarios, promedio_puntajes
        t0 = datetime(2026, 10, 1)
        filas = {"vpd": [(t0 + timedelta(hours=h), 1.0 if h < 24 else 2.0, (0.8, 1.2)) for h in range(48)]}
        p = puntajes_diarios(filas)
        self.assertEqual(list(p.values()), [100, 0])
        self.assertEqual(promedio_puntajes(p), 50)
        self.assertEqual(promedio_puntajes(p, desde=(t0 + timedelta(days=1)).date()), 0)

    def test_catalogo_consistente(self):
        from nucleo.recetas import validar_catalogo, CATALOGO
        self.assertEqual(validar_catalogo(), [])
        self.assertGreaterEqual(len(CATALOGO), 5)


class TestFranjas(unittest.TestCase):
    def test_franjas_horarias(self):
        from nucleo.diagnostico import franjas_horarias
        ahora = datetime(2026, 10, 6, 15, 30)
        filas = [(ahora - timedelta(minutes=5 * i), 1.5 if i < 12 else 1.0, (0.8, 1.2)) for i in range(24 * 12)]
        f = franjas_horarias(filas, ahora)
        self.assertEqual(len(f), 24)
        self.assertEqual(f[-1]["hora"], "15 h")
        self.assertGreater(f[-1]["z"], 0)
        self.assertEqual(f[0]["z"], 0)


class TestRecomendaciones(unittest.TestCase):
    def test_avisa_lo_que_no_puede_corregir(self):
        from nucleo.diagnostico import recomendaciones
        es = [explicar("vpd", 1.8, (0.8, 1.2)), explicar("ph", 7.0, (5.5, 6.5))]
        r = recomendaciones(es, {"extractor", "calefactor"})
        titulos = [x["titulo"] for x in r]
        self.assertIn("Falta un humidificador", titulos)
        self.assertIn("Agua poco ácida", titulos)
        r = recomendaciones(es, {"extractor", "humidificador"})
        self.assertNotIn("Falta un humidificador", [x["titulo"] for x in r])
