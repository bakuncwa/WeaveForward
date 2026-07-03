FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
  && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Bake static files into the image at build time so cold starts skip this step.
# NOTE: GCS static files are NOT updated here — run collectstatic separately
# (e.g. Cloud Run Job) when static assets change in a new deployment.
ENV ENVIRONMENT=development
RUN python manage.py collectstatic --noinput
CMD exec sh -c "python manage.py migrate --noinput && gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120 WeaveForward_Backend.wsgi:application"
