FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec sh -c "python manage.py collectstatic --noinput && daphne -b 0.0.0.0 -p $PORT WeaveForward_Frontend.asgi:application"
