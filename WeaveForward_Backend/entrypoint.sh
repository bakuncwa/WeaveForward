#!/bin/bash

# Wait for database server to be ready and create database if it doesn't exist
echo "Waiting for database server..."
while ! python -c "
import MySQLdb
import os
from dotenv import load_dotenv
load_dotenv()
try:
    if os.getenv('CLOUD_SQL_CONNECTION_NAME'):
        MySQLdb.connect(user=os.getenv('DB_USER', 'root'), passwd=os.getenv('DB_PASSWORD', ''), unix_socket=f'/cloudsql/{os.getenv(\"CLOUD_SQL_CONNECTION_NAME\")}')
    else:
        MySQLdb.connect(host=os.getenv('DB_HOST', '127.0.0.1'), user=os.getenv('DB_USER', 'root'), passwd=os.getenv('DB_PASSWORD', ''), port=int(os.getenv('DB_PORT', 3306)))
except Exception:
    exit(1)
" > /dev/null 2>&1; do
  echo "Database server is unavailable - sleeping..."
  sleep 1
done

echo "Database server is up! Ensuring database exists..."
python init_db.py

# Apply database migrations
echo "Applying database migrations..."
python manage.py migrate --noinput

# Collect static files (ensure latest assets are ready)
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Setup admin user from environment variables
echo "Setting up admin user..."
python manage.py setup_admin

# Start Gunicorn (Cloud Run uses $PORT)
echo "Starting Gunicorn on port $PORT..."
exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 WeaveForward_Backend.wsgi:application
