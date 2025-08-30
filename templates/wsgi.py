"""
WSGI Configuration for Binance Futures Bot
Production-ready WSGI entry point for Gunicorn.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

# Import the Flask application and the SocketIO instance from your main app file
# The variable 'application' is what Gunicorn looks for by default.
from app import socketio
if __name__ == "__main__":
    socketio.run(application)
# Gunicorn will run this 'application' object
application = socketio