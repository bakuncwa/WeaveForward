#!/bin/bash

# Collect static files (ensure latest assets are ready)
echo "Collecting static files for Frontend..."
python manage.py collectstatic --noinput

# Start Daphne ASGI (Cloud Run uses $PORT)
echo "Starting Frontend Daphne on port $PORT..."
exec daphne -b 0.0.0.0 -p $PORT WeaveForward_Frontend.asgi:application
