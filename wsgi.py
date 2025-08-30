# Monkey patch debe ser lo PRIMERO que se ejecute
import eventlet
eventlet.monkey_patch()

import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

# Importar la aplicación Flask después del monkey patch
from app import app as app

# Asegurarse de que la aplicación sea callable
if __name__ == "__main__":
    app.run()