#!/bin/bash

# Collect static files (ensure latest assets are ready)
echo "Collecting static files for Frontend..."
python manage.py collectstatic --noinput

# Start Gunicorn (Cloud Run uses $PORT)
echo "Starting Frontend Gunicorn on port $PORT..."
exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 WeaveForward_Frontend.wsgi:application
