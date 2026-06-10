# GCP Setup & Configuration Guide

This guide covers deploying WeaveForward to Google Cloud Platform using Cloud Run, Cloud SQL, Cloud Storage, Cloud Scheduler, and BigQuery.

---

## Prerequisites

Install and authenticate the `gcloud` CLI, then set your project:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Enable required APIs:

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  cloudbuild.googleapis.com storage.googleapis.com \
  cloudscheduler.googleapis.com bigquery.googleapis.com
```

---

## 1. Cloud Storage (GCS) — Media & Static Files

```bash
# Create bucket
gcloud storage buckets create gs://weaveforward-media \
  --location=asia-southeast1 \
  --uniform-bucket-level-access

# Make publicly readable for media/static file serving
gcloud storage buckets add-iam-policy-binding gs://weaveforward-media \
  --member=allUsers \
  --role=roles/storage.objectViewer

# Grant Cloud Run service account write access
gcloud storage buckets add-iam-policy-binding gs://weaveforward-media \
  --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com \
  --role=roles/storage.objectAdmin
```

Set in backend Cloud Run environment variables:

```
GS_BUCKET_NAME=weaveforward-media
GS_PROJECT_ID=YOUR_PROJECT_ID
```

---

## 2. Cloud SQL (MySQL) — Database

```bash
# Create instance
gcloud sql instances create weaveforward-db \
  --database-version=MYSQL_8_0 \
  --tier=db-f1-micro \
  --region=asia-southeast1

# Create database
gcloud sql databases create weaveforward_db --instance=weaveforward-db

# Set root password
gcloud sql users set-password root \
  --instance=weaveforward-db \
  --password=YOUR_DB_PASSWORD

# Get connection name (needed for Cloud Run)
gcloud sql instances describe weaveforward-db --format="value(connectionName)"
# Output: YOUR_PROJECT_ID:asia-southeast1:weaveforward-db
```

Set in backend Cloud Run environment variables:

```
DB_NAME=weaveforward_db
DB_USER=root
DB_PASSWORD=YOUR_DB_PASSWORD
CLOUD_SQL_CONNECTION_NAME=YOUR_PROJECT_ID:asia-southeast1:weaveforward-db
```

---

## 3. Container Registry — Build & Push Images

```bash
# Build and push backend image
cd WeaveForward_Backend
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/weaveforward-backend

# Build and push frontend image
cd ../WeaveForward_Frontend
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/weaveforward-frontend
```

---

## 4. Cloud Run — Deploy Services

### Backend

```bash
gcloud run deploy weaveforward-backend \
  --image gcr.io/YOUR_PROJECT_ID/weaveforward-backend \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --add-cloudsql-instances YOUR_PROJECT_ID:asia-southeast1:weaveforward-db \
  --set-env-vars "ENVIRONMENT=production,DEBUG=False,\
SECRET_KEY=YOUR_SECRET_KEY,\
DB_NAME=weaveforward_db,DB_USER=root,DB_PASSWORD=YOUR_DB_PASSWORD,\
CLOUD_SQL_CONNECTION_NAME=YOUR_PROJECT_ID:asia-southeast1:weaveforward-db,\
GS_BUCKET_NAME=weaveforward-media,GS_PROJECT_ID=YOUR_PROJECT_ID,\
ALLOWED_HOSTS=weaveforward-backend-xxxx-as.a.run.app,\
AUTH_COOKIE_SECURE=True,\
RESEND_API_KEY=YOUR_RESEND_KEY,\
MAYA_API_SECRET_KEY=YOUR_MAYA_SECRET,\
MAYA_API_PUBLIC_KEY=YOUR_MAYA_PUBLIC,\
MAYA_SANDBOX_BASE_URL=https://pg-sandbox.paymaya.com/payments/v1,\
LALAMOVE_API_KEY=YOUR_LALAMOVE_KEY,\
LALAMOVE_API_SECRET=YOUR_LALAMOVE_SECRET,\
LALAMOVE_BASE_URL=https://rest.sandbox.lalamove.com,\
SCHEDULER_SECRET=YOUR_SCHEDULER_SECRET,\
ADMIN_EMAIL=admin@weaveforward.com,\
ADMIN_PASSWORD=YOUR_ADMIN_PASSWORD,\
CATALOG_CSV_PATH=backend/data/webscraped_data/webscraped_catalog_archive.csv"
```

Note the deployed backend URL — e.g. `https://weaveforward-backend-xxxx-as.a.run.app`

### Frontend

```bash
gcloud run deploy weaveforward-frontend \
  --image gcr.io/YOUR_PROJECT_ID/weaveforward-frontend \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "DEBUG=False,\
SECRET_KEY=YOUR_FRONTEND_SECRET_KEY,\
BACKEND_BASE_URL=https://weaveforward-backend-xxxx-as.a.run.app/api/"
```

### Bootstrap Database (First Deploy Only)

After the backend is deployed for the first time, run migrations and seed the admin account:

```bash
gcloud run jobs create bootstrap \
  --image gcr.io/YOUR_PROJECT_ID/weaveforward-backend \
  --region asia-southeast1 \
  --add-cloudsql-instances YOUR_PROJECT_ID:asia-southeast1:weaveforward-db \
  --set-env-vars "ENVIRONMENT=production,..." \
  --command "python" \
  --args "manage.py,bootstrap_environment"

gcloud run jobs execute bootstrap --region asia-southeast1
```

---

## 5. Cloud Scheduler — Subscription Auto-Renewal

```bash
# Create daily renewal job (midnight PH time = 16:00 UTC)
gcloud scheduler jobs create http weaveforward-renewal \
  --schedule="0 16 * * *" \
  --uri="https://weaveforward-backend-xxxx-as.a.run.app/api/scheduler/renew-subscriptions/" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=YOUR_SCHEDULER_SECRET,Content-Type=application/json" \
  --message-body="{}" \
  --location=asia-southeast1 \
  --time-zone="Asia/Manila"

# Verify job
gcloud scheduler jobs list --location=asia-southeast1
```

---

## 6. BigQuery — Analytics (Optional)

BigQuery is used for analytics exports and reporting. WeaveForward uses Cloud SQL (MySQL) as the primary data store; BigQuery is connected via Cloud SQL federation or scheduled exports.

```bash
# Create dataset
bq mk --dataset --location=asia-southeast1 YOUR_PROJECT_ID:weaveforward_analytics

# Grant Cloud Run service account access
bq add-iam-policy-binding \
  --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com \
  --role=roles/bigquery.dataEditor \
  YOUR_PROJECT_ID:weaveforward_analytics
```

---

## Summary

| Step | Service | Purpose |
|---|---|---|
| 1 | Cloud Storage | Media uploads, static files |
| 2 | Cloud SQL | MySQL database |
| 3 | Container Registry | Docker image storage |
| 4 | Cloud Run (×2) | Backend API + Frontend ASGI |
| 5 | Cloud Scheduler | Daily subscription auto-renewal |
| 6 | BigQuery | Analytics exports (optional) |

---

## Environment Variable Reference

See `WeaveForward_Backend/.env.example` and `WeaveForward_Frontend/.env.example` for the full list of required environment variables and descriptions for each service.
