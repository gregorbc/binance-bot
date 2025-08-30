#!/bin/bash

# Binance Futures Bot - Startup Script
# This script handles the startup process for production deployment

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}=================================${NC}"
    echo -e "${BLUE} Binance Futures Bot v10.5${NC}"
    echo -e "${BLUE} Production Startup Script${NC}"
    echo -e "${BLUE}=================================${NC}"
}

# Check if script is run as root (not recommended)
check_user() {
    if [ "$EUID" -eq 0 ]; then
        print_warning "Running as root is not recommended for security reasons" 
    fi
}

# Check if required files exist
check_requirements() {
    print_status "Checking requirements..."
    
    local required_files=("app.py" "requirements.txt" ".env" "gunicorn.conf.py" "wsgi.py") 
    local missing_files=()
    
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            missing_files+=("$file")
        fi
    done
    
    if [ ${#missing_files[@]} -ne 0 ]; then
        print_error "Missing required files: ${missing_files[*]}"
        exit 1
    fi
    
    if [ ! -d "templates" ] || [ ! -f "templates/index.html" ]; then
        print_warning "Templates directory/index.html not found, creating..."
        mkdir -p templates
    fi
    
    if [ ! -d "static" ]; then
        print_warning "Static directory not found, creating..."
        mkdir -p static
    fi
    
    if [ ! -d "logs" ]; then
        print_warning "Logs directory not found, creating..."
        mkdir -p logs
    fi
}

# Check Python version
check_python() {
    print_status "Checking Python version..."
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is required but not installed"
        exit 1
    fi
    
    local python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
    local required_version="3.8"
    
    if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
        print_error "Python $required_version or higher is required. Found: $python_version"
        exit 1
    fi
    
    print_status "Python version: $python_version ✓"
}

# Setup virtual environment
setup_venv() {
    print_status "Setting up virtual environment..."
    
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        print_status "Virtual environment created"
    else
        print_status "Virtual environment already exists"
    fi
    
    source venv/bin/activate 
    print_status "Virtual environment activated"
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install requirements
    print_status "Installing dependencies from requirements.txt..."
    pip install -r requirements.txt 
    
    # Ensure eventlet is installed for SocketIO
    if ! pip show eventlet &> /dev/null; then
        print_warning "eventlet not found in requirements, installing it for real-time updates..."
        pip install eventlet
    fi
    
    print_status "Dependencies installed ✓"
}

# Check environment variables
check_env() {
    print_status "Checking environment configuration..."
    
    set -a # automatically export all variables
    source .env
    set +a
    
    if [ -z "$BINANCE_API_KEY" ] || [ -z "$BINANCE_API_SECRET" ]; then
        print_error "BINANCE_API_KEY and BINANCE_API_SECRET must be set in .env file"
        print_status "Example .env file:"
        cat .env.example 2>/dev/null || echo "BINANCE_API_KEY=your_key_here"
        exit 1
    fi
    
    if [ -z "$SECRET_KEY" ]; then
        print_warning "SECRET_KEY not set, generating random key..."
        SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        echo "SECRET_KEY=$SECRET_KEY" >> .env
        print_status "SECRET_KEY generated and added to .env"
    fi
    
    print_status "Environment configuration ✓"
}

# Test API connectivity
test_api() {
    print_status "Testing Binance API connectivity..."
    
    python3 -c "
import os
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
testnet = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'

try:
    client = Client(api_key, api_secret, testnet=testnet)
    info = client.futures_exchange_info()
    print('✓ API connection successful')
    print(f\"✓ Connected to {'TESTNET' if testnet else 'MAINNET'}\")
except Exception as e:
    print(f'✗ API connection failed: {e}')
    exit(1)
" || exit 1
    
    print_status "API connectivity ✓"
}

# Initialize database
init_db() {
    print_status "Initializing database..."
    
    python3 -c "
from database import init_db
init_db()
print('✓ Database initialized successfully')
" || { print_error "Failed to initialize database"; exit 1; }
    
    print_status "Database initialization ✓"
}

# Start the application
start_app() {
    print_status "Starting Binance Futures Bot..."
    
    local mode=${1:-"development"}
    
    if [ "$mode" = "production" ]; then
        print_status "Starting in production mode with Gunicorn..."
        # Use exec to replace the shell process with gunicorn
        exec gunicorn --config gunicorn.conf.py wsgi:application
    else
        print_status "Starting in development mode with Flask-SocketIO server..."
        export FLASK_ENV=development
        export DEBUG=true
        # Run app.py directly which uses socketio.run() for a proper dev server
        exec python3 app.py
    fi
}

# Main execution
main() {
    print_header
    
    # Parse command line arguments
    local mode="development"
    local skip_checks=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --production|-p)
                mode="production"
                shift
                ;;
            --skip-checks)
                skip_checks=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  --production, -p    Run in production mode with Gunicorn"
                echo "  --skip-checks       Skip system and API checks"
                echo "  --help, -h          Show this help message"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    if [ "$skip_checks" = false ]; then
        check_user
        check_requirements
        check_python
        setup_venv
        check_env
        test_api
        init_db
    else
        print_warning "Skipping system checks as requested"
        source venv/bin/activate 2>/dev/null || true
    fi
    
    print_status "All checks passed! Starting application..."
    echo
    
    start_app "$mode"
}

# Run main function with all arguments
main "$@"