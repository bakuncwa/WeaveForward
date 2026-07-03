FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput
CMD exec sh -c "daphne -b 0.0.0.0 -p $PORT WeaveForward_Frontend.asgi:application"
