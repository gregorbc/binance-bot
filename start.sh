#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Virtual Environment Setup ---
# Check if the virtual environment directory 'venv' exists.
if [ -d "venv" ]; then
    echo "Activating existing virtual environment."
    source venv/bin/activate
else
    echo "Creating new virtual environment."
    # FIXED: Corrected the typo 'ven极速赛车开奖直播' to 'venv'
    python3 -m venv venv
    source venv/bin/activate
    echo "Upgrading pip and installing requirements..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# --- Flask Environment Configuration ---
export FLASK_ENV=production
export DEBUG=false

# --- Database Initialization ---
# Run the database initialization within the Flask application context.
echo "Initializing the database..."
python3 -c "
from app import app
from database import init_db
with app.app_context():
    init_db()
"
echo "Database initialized."

# --- Start Gunicorn Server ---
# FIXED: Use eventlet worker class and correct module (wsgi:app)
echo "Starting Gunicorn server..."
exec gunicorn --worker-class eventlet -w 1 -b 0.0.0.0:5000 wsgi:app