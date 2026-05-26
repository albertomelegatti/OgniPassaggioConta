#!/usr/bin/env python3
"""
Test script to verify OgniPassaggioConta configuration
Helps identify issues before deploying to Render
"""

import os
import sys
import json
from pathlib import Path

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def print_status(message, status='info'):
    if status == 'ok':
        print(f"{Colors.GREEN}✅ {message}{Colors.RESET}")
    elif status == 'error':
        print(f"{Colors.RED}❌ {message}{Colors.RESET}")
    elif status == 'warning':
        print(f"{Colors.YELLOW}⚠️  {message}{Colors.RESET}")
    elif status == 'info':
        print(f"{Colors.BLUE}ℹ️  {message}{Colors.RESET}")

def check_environment_variables():
    """Check if all required environment variables are set"""
    print("\n" + "="*50)
    print("1. CHECKING ENVIRONMENT VARIABLES")
    print("="*50)
    
    required_vars = [
        'DATABASE_URL',
        'SECRET_KEY',
        'SUPABASE_URL',
        'SERVICE_ROLE_KEY',
        'SUPABASE_BUCKET',
        'MAIL_USERNAME',
        'MAIL_PASSWORD',
        'MAIL_SERVER',
        'MAIL_PORT',
        'MAIL_USE_TLS'
    ]
    
    missing = []
    for var in required_vars:
        if os.getenv(var):
            value = os.getenv(var)
            # Hide sensitive values
            if 'KEY' in var or 'PASSWORD' in var or 'DATABASE' in var:
                value = f"{value[:10]}...{value[-5:]}" if len(value) > 15 else "***"
            print_status(f"{var} is set", 'ok')
        else:
            print_status(f"{var} is NOT set", 'error')
            missing.append(var)
    
    if missing:
        print_status(f"Missing {len(missing)} environment variables!", 'warning')
        return False
    else:
        print_status("All environment variables are set!", 'ok')
        return True

def check_database_connection():
    """Check if we can connect to the database"""
    print("\n" + "="*50)
    print("2. CHECKING DATABASE CONNECTION")
    print("="*50)
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print_status("DATABASE_URL not set, skipping database check", 'warning')
        return False
    
    try:
        import psycopg2
        from urllib.parse import urlparse
        
        # Parse the database URL
        result = urlparse(database_url)
        print_status(f"Database host: {result.hostname}", 'info')
        print_status(f"Database port: {result.port}", 'info')
        print_status(f"Database user: {result.username}", 'info')
        
        # Try to connect
        conn = psycopg2.connect(
            host=result.hostname,
            port=result.port,
            user=result.username,
            password=result.password,
            database="postgres",
            connect_timeout=5
        )
        
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print_status(f"Connected to: {version[0][:50]}...", 'ok')
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print_status(f"Database connection failed: {e}", 'error')
        return False

def check_python_dependencies():
    """Check if all required Python packages are installed"""
    print("\n" + "="*50)
    print("3. CHECKING PYTHON DEPENDENCIES")
    print("="*50)
    
    required_packages = [
        'flask',
        'flask_session',
        'flask_sqlalchemy',
        'flask_mail',
        'psycopg2',
        'dotenv',
        'werkzeug',
        'pillow',
        'supabase'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package)
            print_status(f"{package} is installed", 'ok')
        except ImportError:
            print_status(f"{package} is NOT installed", 'error')
            missing.append(package)
    
    if missing:
        print_status(f"Missing {len(missing)} packages", 'warning')
        print_status(f"Install with: pip install {' '.join(missing)}", 'info')
        return False
    else:
        print_status("All dependencies are installed!", 'ok')
        return True

def check_file_structure():
    """Check if all required files exist"""
    print("\n" + "="*50)
    print("4. CHECKING FILE STRUCTURE")
    print("="*50)
    
    required_files = [
        'main.py',
        'db.py',
        'admin.py',
        'utils.py',
        'requirements.txt',
        'Procfile'
    ]
    
    required_dirs = [
        'templates',
        'static'
    ]
    
    missing = []
    
    for file in required_files:
        if Path(file).exists():
            print_status(f"File exists: {file}", 'ok')
        else:
            print_status(f"File missing: {file}", 'error')
            missing.append(file)
    
    for dir in required_dirs:
        if Path(dir).exists():
            print_status(f"Directory exists: {dir}", 'ok')
        else:
            print_status(f"Directory missing: {dir}", 'error')
            missing.append(dir)
    
    if missing:
        print_status(f"Missing {len(missing)} files/directories", 'warning')
        return False
    else:
        print_status("All files and directories are present!", 'ok')
        return True

def check_flask_app():
    """Try to import and initialize the Flask app"""
    print("\n" + "="*50)
    print("5. CHECKING FLASK APP INITIALIZATION")
    print("="*50)
    
    try:
        print_status("Importing Flask app...", 'info')
        # This will trigger all the initialization
        from main import app
        print_status("Flask app imported successfully!", 'ok')
        print_status(f"App name: {app.name}", 'info')
        print_status(f"Blueprints: {list(app.blueprints.keys())}", 'info')
        return True
    except Exception as e:
        print_status(f"Failed to import Flask app: {e}", 'error')
        import traceback
        traceback.print_exc()
        return False

def main():
    print(f"\n{Colors.BLUE}{'='*50}")
    print("OgniPassaggioConta - Configuration Test")
    print(f"{'='*50}{Colors.RESET}")
    
    results = []
    
    # Run all checks
    results.append(("Environment Variables", check_environment_variables()))
    results.append(("Database Connection", check_database_connection()))
    results.append(("Python Dependencies", check_python_dependencies()))
    results.append(("File Structure", check_file_structure()))
    results.append(("Flask App Initialization", check_flask_app()))
    
    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    
    all_ok = True
    for check_name, result in results:
        status = 'ok' if result else 'error'
        print_status(f"{check_name}: {'PASS' if result else 'FAIL'}", status)
        if not result:
            all_ok = False
    
    print("\n" + "="*50)
    if all_ok:
        print_status("All checks passed! Ready for deployment.", 'ok')
        print("="*50 + "\n")
        return 0
    else:
        print_status("Some checks failed. Review the errors above.", 'error')
        print("="*50 + "\n")
        return 1

if __name__ == '__main__':
    sys.exit(main())
