# Plataforma de control y trazabilidad para cultivos intensivos

Prototipo del Proyecto Final (Ingeniería en Informática).

## Estructura

```
plataforma/
├── nucleo/                 Lógica pura en Python (sin Django), testeada aparte
│   ├── vpd.py              Presión de vapor, VPD de hoja, humedad absoluta
│   ├── reglas.py           Reglas de control: extracción escalonada, histéresis, calefacción
│   ├── controlador.py      Controlador con estado (anti-ciclado)
│   ├── drivers.py          Drivers por marca: simulado, Tuya/Smart Life, Shelly
│   └── simulacion.py       Modelo simplificado de invernadero para pruebas
├── cultivo/                App Django: modelo de datos, dashboard, APIs
│   └── management/commands/
│       ├── simular.py           Genera datos de demostración (historial y en vivo)
│       └── servicio_control.py  Servicio real: MQTT + reglas + drivers
├── invernadero/            Configuración del proyecto Django
├── tests_nucleo/           Pruebas del núcleo
└── docker-compose.yml      PostgreSQL/TimescaleDB + Mosquitto (producción)
```

## Puesta en marcha en Windows

Requisito: Python 3.11 o superior (python.org, marcar "Add Python to PATH").

Abrir PowerShell en la carpeta `plataforma` y ejecutar:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py makemigrations cultivo
python manage.py migrate
python manage.py simular --reset
python manage.py runserver
```

Si PowerShell bloquea la activación del entorno, ejecutar una vez:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Abrir http://127.0.0.1:8000 e ingresar con **demo / demo1234** (usuario de desarrollo que crea `simular`).

Para ver el panel "en vivo", abrir otra terminal (con el entorno activado) y ejecutar:

```powershell
python manage.py simular --vivo
```

Genera una lectura cada 10 segundos. Si prendés o apagás un extractor desde el panel, pasa a modo manual y la simulación lo respeta.

## Pruebas

```powershell
python -m unittest discover tests_nucleo   # núcleo: VPD, reglas, drivers, simulación
python manage.py test cultivo              # web: páginas, APIs, comandos manuales
```

## Datos simulados

`simular --reset` genera 28 días: 14 con control por horario (línea base) y 14 con control en lazo cerrado. Usa el **mismo motor de reglas** que el servicio real. Son datos sintéticos para desarrollar y mostrar la plataforma. **No son resultados del experimento**: los del Capítulo 7 salen del invernadero real.

## Conexión con hardware real (próximos pasos)

1. Nodo ESP32 publica lecturas por MQTT en `invernadero/<id_sala>/lecturas`.
2. `docker compose up -d` levanta Mosquitto (y TimescaleDB).
3. Cargar los actuadores en Administración con driver `tuya` y su `config`:
   `{"device_id": "...", "ip": "192.168.x.x", "local_key": "...", "version": 3.3}`
4. `pip install paho-mqtt tinytuya` y `python manage.py servicio_control --sala 1`.
