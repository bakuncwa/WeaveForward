# WeaveForward

---

**ML Model Repository:** https://github.com/bakuncwa/weaveforward_fiber_model
**Mock HTML Files:** https://github.com/dave34458/WeaveForward-Mock-HTML-Files

---

## Project Overview

WeaveForward provides a circular economy platform that streamlines textile donations through geolocation mapping, standardized donation processes, donation tracking, delivery integration, and donation impact dashboards. The system also supports material-based matching to assist TUABs in recognizing suitable donations more effectively and efficiently. Designed for donors and TUABs, WeaveForward improves convenience, trust, and coordination across the textile donation lifecycle.

### Key Features
- Donor platform for browsing and submitting donations
- TUAB (organization) inventory and donation management
- AI-powered donation matching recommendations using machine learning
- Circular economy impact tracking and dashboards
- Role-based access control (RBAC) for multi-tenant authentication
- Payment and subscription handling
- Comprehensive impact analytics

---

## Architecture & Security Specifications

This project adheres to formal proposal specifications, featuring a **physically decoupled 3-tier native GCP architecture**. It is engineered for high availability and scalability, ready for deployment using **Cloud SQL** and dual **Cloud Run** instances for independent service orchestration.

---

### Core Technical Standards
- **Security & Authentication**: Implements industry-standard `bcrypt` password hashing and `simple-jwt` (JSON Web Tokens) for secure, stateless authentication.
- **Hardened Defense**: Built-in security specifications to mitigate **CORS**, **CSS**, and **XSS** vulnerabilities, ensuring robust protection across all application layers.
- **Cloud-Native Design**: Architected for seamless integration with Google Cloud Platform services, facilitating a production-ready environment.

---

## Technology Stack

| Category | Technology / Library |
|---|---|
| Backend / API | Python, Django, Django REST Framework |
| Machine Learning | CatBoost, scikit-learn, Optuna, SHAP |
| Data Processing | pandas, NumPy, PySpark / Spark SQL |
| Geospatial | geopy (Nominatim OSM), haversine distance |
| Data Scraping | requests, BeautifulSoup, Selenium |
| Visualization | Matplotlib, Seaborn |
| Storage | Parquet (Spark), CSV, CatBoost .cbm binary |
| Notebook Environment | Jupyter (VS Code), ipywidgets (live training chart) |
| Hyperparameter Tuning | Optuna (30 trials, 3-fold stratified CV) |

---

## Project Completion Status
**Overall Progress: ~95%**

Core infrastructure are fully operational. Final development is focused on deployment in Cloud Storage, Cloud SQL, Cloud Scheduler, and Cloud Runs for user acceptance testing (UAT).

---

## Getting Started

### Prerequisites
* **Python 3.12**: Ensure Python 3.12 is installed on your system.
* **MySQL Server**: A local MySQL instance must be running.
  * **Windows**: [Download MySQL Installer](https://dev.mysql.com/downloads/installer/)
  * **macOS**: [Download MySQL DMG Installer](https://dev.mysql.com/downloads/mysql/) or install via Homebrew: `brew install mysql`.

### macOS Help Notes
If `pip install` fails with a `mysql_config` error, install the client libraries and point Python to them:
```bash
brew install mysql-client pkg-config

# For Apple Silicon (M1/M2/M3):
export PKG_CONFIG_PATH="/opt/homebrew/opt/mysql-client/lib/pkgconfig"

# For Intel Macs:
export PKG_CONFIG_PATH="/usr/local/opt/mysql-client/lib/pkgconfig"
```

---

## 1. Get the Project

Clone the repository and enter the project root:

```powershell
git clone <repository-url>
cd WeaveForward
```

If you already have the repository, open a terminal in the project root.

---

## 2. Configure Backend Environment

Create or edit `WeaveForward_Backend/.env`.

For local development, it must use local MySQL:

```env
ENVIRONMENT=development
DEBUG=True
SECRET_KEY=django-insecure-local-weaveforward-dev-key
ALLOWED_HOSTS=127.0.0.1,localhost
CORS_ALLOWED_ORIGINS=http://127.0.0.1:8001,http://localhost:8001
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8001,http://localhost:8001

DB_NAME=weaveforward_db
DB_USER=YOUR_MYSQL_USER
DB_PASSWORD=YOUR_MYSQL_PASSWORD
DB_HOST=127.0.0.1
DB_PORT=3306

AUTH_COOKIE_SECURE=False
CATALOG_CSV_PATH=backend/data/webscraped_data/webscraped_catalog_archive.csv
DJANGO_ML_DIR=fiber_match_api/models

SCHEDULER_SECRET=dev-scheduler-secret-key-123

RESEND_API_KEY=YOUR_RESEND_API_KEY

MAYA_API_SECRET_KEY=YOUR_MAYA_SECRET_KEY
MAYA_API_PUBLIC_KEY=YOUR_MAYA_PUBLIC_KEY
MAYA_SANDBOX_BASE_URL=https://pg-sandbox.paymaya.com/payments/v1

LALAMOVE_API_KEY=YOUR_LALAMOVE_API_KEY
LALAMOVE_API_SECRET=YOUR_LALAMOVE_API_SECRET
LALAMOVE_BASE_URL=https://rest.sandbox.lalamove.com
```

Use any local MySQL user that can create databases and modify tables. The MySQL `root` user works if that is what you configured during installation. Keep `DB_HOST=127.0.0.1` and `DB_PORT=3306` unless your local MySQL uses a custom host or port.

Use real sandbox/API keys for Resend, Maya, and Lalamove if you need to test email, payment, or delivery flows locally. Placeholder values are enough for setup, migrations, fixture loading, and basic login testing only.

## 3. Set Up Backend

1. **Navigate to the Backend Directory**:
   ```powershell
   cd WeaveForward_Backend
   ```

2. **Initialize and Activate Virtual Environment**:
   ```powershell
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

---

## 4. Initialize the Local Backend Database

Make sure MySQL is running, then run the backend bootstrap:

```powershell
python manage.py bootstrap_environment
```

This creates `weaveforward_db`, applies migrations, and loads the product catalog.

Then load the deployment fixtures:

```powershell
python deployment/cloudsql/main.py
```

This loads the demo/UAT fixture data such as users, uploads, donations, inventory, subscriptions, orders, payments, and audit trail records.

---

## 5. Start the Backend Server

In the backend terminal:

```powershell
python manage.py runserver 127.0.0.1:8000
```

The backend API will be accessible at:

```text
http://127.0.0.1:8000/api/
```

The backend root `/` may return `404`, which is expected because API routes live under `/api/`.

---

## 6. Set Up Frontend

Open a new terminal from the project root.

1. **Navigate to the Frontend Directory**:
   ```powershell
   cd WeaveForward_Frontend
   ```

2. **Initialize and Activate Virtual Environment**:
   ```powershell
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Apply Frontend Database Migrations**:
   ```powershell
   python manage.py migrate
   ```

---

## 7. Start the Frontend Server

In the frontend terminal:

```powershell
python manage.py runserver 8001
```

The frontend will be accessible at:

```text
http://127.0.0.1:8001/
```

> [!NOTE]
> The frontend is powered by **Daphne ASGI** (integrated directly into the Django development server). This allows it to natively support async middleware and asynchronous backend proxy calls without locking files on Windows during local development.

---

## 8. Verify Local Login

Open the frontend and log in with:

| Field | Value |
| :--- | :--- |
| **Email** | `admin@weaveforward.com` |
| **Password** | `SecureAdminPassword123` |

---

## Git Workflow Guide

### Getting Started

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd weaveforward_system
   ```

2. Create a feature branch following the naming convention above

3. Set up your development environment with required dependencies

4. Make your changes and commit regularly

5. Push your feature branch and create a pull request for review

### Branch Naming Convention

Use the following format for creating feature branches:

```
<feature-name>-v<major>.<minor>.<patch>
```

### Examples:
- `login-v1.0.0` - Initial Login feature
- `register-v1.0.0` - Initial Register feature
- `login-v1.0.1` - Login feature bug fix or patch
- `donate-v1.0.0` - Donation feature
- `inventory-management-v1.0.0` - Inventory management feature
- `rbac-routing-v1.0.0` - Role-based access control feature

### Creating a Feature Branch

```bash
# Create and checkout a new feature branch
git branch <feature-name>-v<version>
git checkout <feature-name>-v<version>

# Or use the shorthand
git checkout -b <feature-name>-v<version>
```

### Example Workflow:

```bash
# Create login feature branch
git checkout -b login-v1.0.0

# Make changes to your feature
# ... edit files ...

# Stage and commit changes
git add .
git commit -m "feat: implement login functionality"

# Push branch to remote
git push origin login-v1.0.0

# Create pull request on GitHub when ready for review
```

### Merging a Feature Branch

```bash
# Switch to main/development branch
git checkout main

# Pull latest changes
git pull origin main

# Merge feature branch
git merge <feature-name>-v<version>

# Delete branch locally after merging
git branch -d <feature-name>-v<version>

# Delete branch on remote
git push origin --delete <feature-name>-v<version>
```

### Useful Git Commands

```bash
# List all local branches
git branch

# List all remote branches
git branch -r

# Delete a local branch
git branch -d <branch-name>

# Rename current branch
git branch -m <new-branch-name>

# View commit history of a branch
git log <branch-name>

# Switch between branches
git checkout <branch-name>

# Check current branch status
git status
```

---

## Development Checklist

### Phase 1: Infrastructure & Setup

Required before feature development:

- [x] Github Repository Set-up + Git commands in README.md
- [x] Django SQL to Google Cloud Storage + BigQuery + Cloud Run + Scheduler + Database Migrations Set-Up
- [x] Django RBAC Routing for Authentication and Authorization

### Phase 2: Core Authentication

Essential user management features:

- [x] Register (Donor/TUAB/Admin)
- [x] Login (+ Google SSO)

### Phase 3: Donor Features

Features for Donor user role:

- [x] Browse TUAB
- [x] View TUAB
- [x] Submit Donation
- [x] View Donation
- [x] Edit Donation
- [x] Cancel Donation
- [x] View Donation Impact Dashboard
- [x] Update Account Information
- [x] Donor Features Blackbox Selenium Test Script

### Phase 4: TUAB Features

Features for TUAB (Organization) user role:

- [x] View Inventory Items
- [x] Update Inventory Items
- [x] Delete Inventory Items
- [x] View Incoming Donations
- [x] Update Incoming Donations
- [x] Archive Incoming Donations
- [x] View Match Donation Recommendations (CatBoostAI ML Model Integration with DB)
- [x] View Circular Economy Impact Dashboard
- [x] Subscribe for Premium Features
- [x] View Payment History
- [x] Update Account Information
- [x] TUAB Features Blackbox Selenium Test Script

### Phase 5: Admin Features

Features for Admin user role:

- [x] View Donors
- [x] Add Donors
- [x] Edit Donors
- [x] Archive Donors
- [x] View TUABs
- [x] Add TUABs
- [x] Edit TUABs
- [x] Archive TUABs
- [x] View Donations
- [x] Edit Donations
- [x] Archive Donations
- [x] View Donation Impact Dashboard
- [x] View Circular Economy Impact Dashboard
- [x] View Payments
- [x] Admin Features Blackbox Selenium Test Script

### Phase 6: Testing & Validation

System testing and user acceptance testing:

- [x] Full System Dry Run #1 (with Capstone Adviser)
- [ ] Revisions #1
- [ ] Full System Dry Run #2 (internal)
- [ ] Revisions #2
- [ ] UAT GForm & Interview - Donor
- [ ] UAT GForm & Interview - TUAB

---

## GCP Deployment Instructions

This section covers deploying WeaveForward to Google Cloud Platform using Cloud Run (backend + frontend), Cloud SQL (MySQL), Cloud Storage (media/static files), and Cloud Scheduler (scheduled jobs).

### Prerequisites

- `gcloud` CLI installed and authenticated
- A GCP project with billing enabled
- Enable required APIs:

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  cloudbuild.googleapis.com storage.googleapis.com cloudscheduler.googleapis.com
```

---

### Step 1 — Cloud SQL (MySQL)

```bash
gcloud sql instances create weaveforward-db \
  --database-version=MYSQL_8_0 \
  --tier=db-f1-micro \
  --region=asia-southeast1

gcloud sql databases create weaveforward_db --instance=weaveforward-db

gcloud sql users set-password root --instance=weaveforward-db --password=YOUR_DB_PASSWORD
```

Note the connection name for use in later steps: `YOUR_PROJECT:asia-southeast1:weaveforward-db`

---

### Step 2 — Cloud Storage Bucket (Media & Static Files)

```bash
gcloud storage buckets create gs://weaveforward-media \
  --location=asia-southeast1 \
  --uniform-bucket-level-access

gcloud storage buckets add-iam-policy-binding gs://weaveforward-media \
  --member=allUsers --role=roles/storage.objectViewer
```

---

### Step 3 — Create Dockerfiles

Neither project ships with a Dockerfile. Create one in each directory before building.

**`WeaveForward_Backend/Dockerfile`:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec sh -c "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 WeaveForward_Backend.wsgi:application"
```

**`WeaveForward_Frontend/Dockerfile`:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec sh -c "python manage.py collectstatic --noinput && daphne -b 0.0.0.0 -p $PORT WeaveForward_Frontend.asgi:application"
```

---

### Step 4 — Build and Push Images

```bash
cd WeaveForward_Backend
gcloud builds submit --tag gcr.io/YOUR_PROJECT/weaveforward-backend

cd ../WeaveForward_Frontend
gcloud builds submit --tag gcr.io/YOUR_PROJECT/weaveforward-frontend
```

---

### Step 5 — Deploy Backend to Cloud Run

```bash
gcloud run deploy weaveforward-backend \
  --image gcr.io/YOUR_PROJECT/weaveforward-backend \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --add-cloudsql-instances YOUR_PROJECT:asia-southeast1:weaveforward-db \
  --set-env-vars "ENVIRONMENT=production,DEBUG=False,SECRET_KEY=YOUR_SECRET_KEY,\
DB_NAME=weaveforward_db,DB_USER=root,DB_PASSWORD=YOUR_DB_PASSWORD,\
CLOUD_SQL_CONNECTION_NAME=YOUR_PROJECT:asia-southeast1:weaveforward-db,\
GS_BUCKET_NAME=weaveforward-media,GS_PROJECT_ID=YOUR_PROJECT,\
ALLOWED_HOSTS=*.run.app,AUTH_COOKIE_SECURE=True,\
RESEND_API_KEY=...,LALAMOVE_API_KEY=...,LALAMOVE_API_SECRET=...,\
LALAMOVE_BASE_URL=https://rest.sandbox.lalamove.com,\
MAYA_API_SECRET_KEY=...,MAYA_API_PUBLIC_KEY=...,\
MAYA_SANDBOX_BASE_URL=https://pg-sandbox.paymaya.com/payments/v1,\
SCHEDULER_SECRET=...,ADMIN_EMAIL=admin@weaveforward.com,ADMIN_PASSWORD=..."
```

Note the deployed backend URL (e.g. `https://weaveforward-backend-xxxx-as.a.run.app`).

---

### Step 6 — Deploy Frontend to Cloud Run

```bash
gcloud run deploy weaveforward-frontend \
  --image gcr.io/YOUR_PROJECT/weaveforward-frontend \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "BACKEND_BASE_URL=https://weaveforward-backend-xxxx-as.a.run.app/api/,\
ENVIRONMENT=production,SECRET_KEY=YOUR_FRONTEND_SECRET_KEY,\
ALLOWED_HOSTS=*.run.app,AUTH_COOKIE_SECURE=True"
```

---

### Step 7 — Cloud Scheduler (Subscription Auto-Renewal)

```bash
gcloud scheduler jobs create http weaveforward-renewal \
  --schedule="0 0 * * *" \
  --uri="https://weaveforward-backend-xxxx-as.a.run.app/api/scheduler/renew-subscriptions/" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=YOUR_SCHEDULER_SECRET" \
  --location=asia-southeast1
```

---

### Step 8 — Update ALLOWED_HOSTS

Once both services are deployed, update `ALLOWED_HOSTS` in each Cloud Run service's environment variables to include the actual `.run.app` URLs, then redeploy.

---

### Deployment Summary

| Component | GCP Service |
|---|---|
| Backend API (Django/Gunicorn) | Cloud Run |
| Frontend (Django/Daphne ASGI) | Cloud Run |
| MySQL database | Cloud SQL |
| Media & static files | Cloud Storage |
| Scheduled jobs (auto-renewal) | Cloud Scheduler |
| Container images | Container Registry (`gcr.io`) |

---

## Troubleshooting and Maintenance

### Database Connection Issues (Backend)
If the backend application fails to connect to MySQL, verify that the MySQL service is active and that the credentials in `WeaveForward_Backend/.env` match your local configuration.

---

## Webhook & ngrok Configuration

For local development of features requiring external callbacks (like Maya payment processing), the backend uses an ngrok tunnel to expose the local server to the internet.

**Local webhook URL format:**

```text
https://YOUR_NGROK_DOMAIN/api/webhooks
```

Before using the webhook locally, include your ngrok domain in `WeaveForward_Backend/.env`:

```env
ALLOWED_HOSTS=127.0.0.1,localhost,YOUR_NGROK_DOMAIN
```

Restart the backend after changing `ALLOWED_HOSTS`, then start it on port `8000`:

```powershell
python manage.py runserver 127.0.0.1:8000
```

In a separate terminal, start ngrok:

```powershell
ngrok http 8000
```

Copy the HTTPS forwarding domain that ngrok gives you, then use:

```text
https://YOUR_NGROK_DOMAIN/api/webhooks
```

Maya/Lalamove webhooks can now be forwarded to the local backend through that ngrok URL.
