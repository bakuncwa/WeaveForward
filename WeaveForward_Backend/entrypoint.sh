#!/bin/bash
set -e

# Wait for database server to be ready
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

echo "Database server is up."

# Apply database migrations on startup so new app revisions can serve the latest schema.
echo "Applying database migrations..."
python manage.py migrate --noinput

# Collect static files to ensure the runtime has the latest compiled asset set.
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start Gunicorn (Cloud Run uses $PORT)
echo "Starting Gunicorn on port $PORT..."
exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 WeaveForward_Backend.wsgi:application
