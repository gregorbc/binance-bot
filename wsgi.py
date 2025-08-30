"""
WSGI config for the Binance Futures Bot project.
It exposes the WSGI callable as a module-level variable named ``application``.
This file is intended for use with a WSGI server like Gunicorn.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
# This ensures that Gunicorn has access to the same environment as a local run
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

# Import the main Flask app and the SocketIO instance.
# For Gunicorn with eventlet/gevent workers, it's crucial to pass the SocketIO instance
# which wraps the Flask app.
from app import app, socketio

# The 'application' variable is what Gunicorn (and other WSGI servers) will look for.
application = socketio

# Optional: If you need to run the app directly for debugging without the main block in app.py
if __name__ == "__main__":
    # This part is generally not used when deploying with Gunicorn,
    # but it can be useful for testing the WSGI entry point.
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    print(f"Starting development server from wsgi.py on http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug)