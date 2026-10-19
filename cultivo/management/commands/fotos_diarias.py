"""Saca la foto diaria de cada cámara (para el time-lapse).

    python manage.py fotos_diarias            # revisa una vez y termina
    python manage.py fotos_diarias --seguir   # queda corriendo y revisa cada minuto

El servicio de control y la simulación en vivo ya lo hacen solos; este comando
sirve para correrlo aparte (por ejemplo, desde el Programador de tareas de Windows).
"""
import time

from django.core.management.base import BaseCommand

from cultivo.fotos import sacar_fotos_diarias


class Command(BaseCommand):
    help = "Saca la foto diaria de cada cámara que todavía no la tenga hoy."

    def add_arguments(self, parser):
        parser.add_argument("--seguir", action="store_true", help="Queda corriendo y revisa cada minuto")

    def handle(self, *args, **o):
        while True:
            sacadas, errores = sacar_fotos_diarias()
            for foto in sacadas:
                self.stdout.write(self.style.SUCCESS(f"Foto guardada: {foto}"))
            for cam, error in errores:
                self.stderr.write(f"{cam}: {error}")
            if not o["seguir"]:
                return
            time.sleep(60)
