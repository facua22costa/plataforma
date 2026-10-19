@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
echo Generando lecturas simuladas cada 10 segundos. Cerra esta ventana para detener.
python manage.py simular --vivo
pause
