# gunicorn.conf.py
import multiprocessing

# Configuración de Gunicorn
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "eventlet"
bind = "0.0.0.0:5000"
reload = False
preload_app = True
timeout = 120