#!/bin/bash

# Termina el script inmediatamente si un comando falla
set -e

# Comprueba si el directorio del entorno virtual 'venv' existe
if [ -d "venv" ]; then
    echo "Activando entorno virtual existente."
    source venv/bin/activate
else
    echo "Creando nuevo entorno virtual."
    python3 -m venv venv
    source venv/bin/activate
    echo "Instalando dependencias..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# Carga variables de entorno desde .env si existe
if [ -f ".env" ]; then
    echo "Cargando variables de entorno desde .env..."
    set -a
    source .env
    set +a
fi

# Configura las variables de entorno para producción
export FLASK_ENV=production
export DEBUG=false

# Inicializa la base de datos
echo "Inicializando la base de datos..."
python3 -c "from database import init_db; init_db()"

# Inicia la aplicación usando Gunicorn con eventlet
echo "Iniciando el servidor Gunicorn..."
exec gunicorn --worker-class eventlet -w 1 -b 0.0.0.0:5000 wsgi:application