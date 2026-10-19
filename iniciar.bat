@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === 1/5 Entorno virtual ===
if not exist ".venv\Scripts\python.exe" python -m venv .venv
call ".venv\Scripts\activate.bat"
if errorlevel 1 goto error

echo.
echo === 2/5 Instalando dependencias ===
python -m pip install -q -r requirements.txt
if errorlevel 1 goto error

echo.
echo === 3/5 Base de datos ===
python manage.py makemigrations cultivo
python manage.py migrate
if errorlevel 1 goto error

echo.
echo === 4/5 Datos de demostracion ===
if not exist "datos_demo.ok" (
    python manage.py simular --reset
    if errorlevel 1 goto error
    echo ok> datos_demo.ok
) else (
    echo Ya estaban cargados. Para regenerarlos, borra el archivo datos_demo.ok
)

echo.
echo === 5/5 Servidor ===
echo Abri en el navegador:  http://127.0.0.1:8000   (usuario demo / demo1234)
echo NO cierres esta ventana mientras uses el sistema.
echo.
python manage.py runserver
goto fin

:error
echo.
echo *** Hubo un error. Copia todo el texto de esta ventana y pasaselo a Claude. ***

:fin
echo.
pause
