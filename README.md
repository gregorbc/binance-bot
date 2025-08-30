# Binance Futures Bot v10.5

![Panel de Control](https://user-images.githubusercontent.com/username/repo/screenshot.png) <!-- Reemplaza esto con una captura de pantalla de tu panel -->

Un bot de trading automatizado para Binance Futures, construido con Flask y SQLAlchemy, que cuenta con un panel de control web profesional para monitoreo y gestión en tiempo real.

---

## Características Principales

- **Panel de Control Profesional:** Interfaz web moderna y responsiva construida con Flask y Chart.js para monitorear el rendimiento en tiempo real.
- **Estrategia de Trading Automatizada:** Implementa una estrategia basada en el cruce de Medias Móviles Exponenciales (EMA) y el Índice de Fuerza Relativa (RSI).
- **Gestión de Riesgo Avanzada:**
    - Stop Loss y Take Profit fijos.
    - **Trailing Stop dinámico** para proteger ganancias.
    - Gestión de riesgo por operación (porcentaje del balance).
- **Análisis y Optimización:**
    - Módulo de análisis de rendimiento por símbolo.
    - Sugerencias automáticas de apalancamiento basadas en la volatilidad y el `Profit Factor`.
- **Operativa Flexible:**
    - Trading 100% automatizado.
    - Posibilidad de **ejecutar trades manuales** directamente desde el panel.
    - Cierre manual de posiciones con un solo clic.
- **Configuración Dinámica:** Modifica parámetros clave como el apalancamiento, el margen por operación y la configuración de la estrategia directamente desde la interfaz web, sin reiniciar el bot.
- **Historial Detallado:** Almacenamiento persistente de todos los trades en una base de datos MySQL, con visualización y filtrado en el panel.
- **Listo para Producción:** Incluye configuración para Gunicorn, un script de inicio robusto (`start.sh`) y ejemplos para despliegue con Systemd y Nginx.

## Estructura del Proyecto

```
binance-futures-bot/
├── app.py              # Aplicación principal Flask y lógica del bot
├── database.py         # Modelos y configuración de base de datos (SQLAlchemy)
├── gunicorn.conf.py    # Configuración de Gunicorn para producción
├── requirements.txt    # Dependencias de Python
├── start.sh            # Script de inicio para desarrollo y producción
├── wsgi.py             # Punto de entrada WSGI para Gunicorn
├── .env.example        # Ejemplo de variables de entorno
├── .gitignore          # Archivos a ignorar por Git
├── README.md           # Este archivo
├── templates/
│   └── index.html      # Interfaz web del panel de control
├── static/             # Archivos estáticos (CSS, JS, imágenes) - (vacío por defecto)
└── logs/               # Directorio para archivos de log (creado automáticamente)
```

## Stack Tecnológico

- **Backend:** Python, Flask, Flask-SocketIO
- **Cliente Binance:** `python-binance`
- **Base de Datos:** SQLAlchemy, MySQL
- **Frontend:** HTML5, CSS3, JavaScript, Chart.js
- **Servidor WSGI:** Gunicorn, Eventlet
- **Despliegue:** Systemd, Nginx (recomendado)

---

## Instalación

Sigue estos pasos para poner en marcha el bot en tu propio servidor (se recomienda Ubuntu 20.04 o superior).

### 1. Clonar el Repositorio

```bash
git clone https://github.com/gregorbc/binance-futures-bot.git
cd binance-futures-bot
```

### 2. Configurar Variables de Entorno

Copia el archivo de ejemplo y edítalo con tus propias credenciales.

```bash
cp .env.example .env
nano .env
```

Rellena las variables:
```ini
# Binance API Configuration
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
BINANCE_TESTNET=true  # 'true' para testnet, 'false' para real

# Application Configuration
SECRET_KEY=your_strong_secret_key_here # Puedes generar una con: python3 -c "import secrets; print(secrets.token_hex(32))"

# Database Configuration
MYSQL_USER=your_db_user
MYSQL_PASSWORD=your_db_password
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=binance
```

### 3. Configurar Base de Datos MySQL

Instala el servidor MySQL y crea la base de datos y el usuario.

```bash
# Instalar servidor MySQL
sudo apt update
sudo apt install mysql-server -y

# Acceder a MySQL
sudo mysql

# Ejecutar los siguientes comandos SQL:
CREATE DATABASE binance;
CREATE USER 'your_db_user'@'localhost' IDENTIFIED BY 'your_db_password';
GRANT ALL PRIVILEGES ON binance.* TO 'your_db_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 4. Instalar Dependencias del Sistema y Python

```bash
# Instalar dependencias del sistema
sudo apt install python3-pip python3-venv python3-dev build-essential -y

# Crear y activar entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias de Python
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Inicializar la Base de Datos

Este comando creará las tablas necesarias en tu base de datos.

```bash
python3 -c "from database import init_db; init_db()"
```

## Ejecución

El script `start.sh` facilita el inicio del bot en diferentes modos.

### Modo Desarrollo

Usa el servidor de desarrollo de Flask. Ideal para pruebas y depuración.

```bash
./start.sh
```

### Modo Producción

Usa **Gunicorn** como servidor WSGI, que es mucho más robusto y eficiente.

```bash
./start.sh --production
```

El panel de control estará disponible en `http://<tu_ip_del_servidor>:5000`.

---

## Despliegue Avanzado (Recomendado)

Para un despliegue robusto en producción, se recomienda usar **Systemd** para gestionar el proceso del bot y **Nginx** como proxy inverso.

### 1. Crear Servicio Systemd

Crea un archivo de servicio para que el bot se ejecute como un demonio y se reinicie automáticamente.

**Crear el archivo:**
```bash
sudo nano /etc/systemd/system/binance-bot.service
```

**Pega el siguiente contenido** (ajusta `User` y `WorkingDirectory`):
```ini
[Unit]
Description=Binance Futures Bot Service
After=network.target mysql.service

[Service]
User=ubuntu  # El usuario con el que se ejecutará el bot
Group=www-data
WorkingDirectory=/home/ubuntu/binance-futures-bot # Ruta completa a tu proyecto
Environment="PATH=/home/ubuntu/binance-futures-bot/venv/bin"
ExecStart=/home/ubuntu/binance-futures-bot/venv/bin/gunicorn --config gunicorn.conf.py wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Activar y gestionar el servicio:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable binance-bot
sudo systemctl start binance-bot
sudo systemctl status binance-bot # Para ver el estado
```

### 2. Configurar Nginx como Proxy Inverso

Nginx servirá el contenido web y redirigirá el tráfico al proceso de Gunicorn. Esto también facilita la configuración de un dominio y SSL.

**Crear archivo de configuración de Nginx:**
```bash
sudo nano /etc/nginx/sites-available/binance-bot
```

**Pega la siguiente configuración:**
```nginx
server {
    listen 80;
    server_name tu_dominio.com www.tu_dominio.com; # Opcional: si tienes un dominio

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Necesario para que Socket.IO funcione correctamente
    location /socket.io {
        proxy_pass http://127.0.0.1:5000/socket.io;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

**Activar el sitio y reiniciar Nginx:**
```bash
sudo ln -s /etc/nginx/sites-available/binance-bot /etc/nginx/sites-enabled/
sudo nginx -t # Probar la configuración
sudo systemctl restart nginx
```

Ahora podrás acceder a tu panel a través de `http://<tu_ip_del_servidor>`.

## Seguridad

- **Firewall:** Configura `ufw` para permitir solo el tráfico necesario (SSH, HTTP, HTTPS).
- **API Keys:** Crea API keys en Binance con permisos restringidos únicamente a "Habilitar Futuros". No habilites retiros.
- **Variables de Entorno:** Nunca subas tu archivo `.env` a GitHub. El archivo `.gitignore` ya está configurado para prevenirlo.

## Licencia

Este proyecto está bajo la Licencia MIT. Consulta el archivo `LICENSE` para más detalles.

## Descargo de Responsabilidad

El trading de criptomonedas, especialmente con apalancamiento, conlleva un alto riesgo financiero. Este software se proporciona "tal cual", sin garantías de ningún tipo. Úsalo bajo tu propio riesgo. El autor, `gregorbc`, no se hace responsable de posibles pérdidas financieras.

---
*Creado por @gregorbc - 2025-08-30*
