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

To ensure cross-platform compatibility and avoid path-related errors, this repository includes the environment configuration (`.env`) but requires you to initialize your own local virtual environment.

### Prerequisites
* **Python 3.12**: Ensure Python 3.12 is installed on your system.
* **MySQL Server**: A local MySQL instance must be running.
  * **Windows**: [Download MySQL Installer](https://dev.mysql.com/downloads/installer/)
  * **macOS**: [Download MySQL DMG Installer](https://dev.mysql.com/downloads/mysql/) or install via Homebrew: `brew install mysql`.

### macOS Help Notes
If `pip install` fails with a `mysql_config` error, you need to install the client libraries and point Python to them:
```bash
brew install mysql-client pkg-config

# For Apple Silicon (M1/M2/M3):
export PKG_CONFIG_PATH="/opt/homebrew/opt/mysql-client/lib/pkgconfig"

# For Intel Macs:
export PKG_CONFIG_PATH="/usr/local/opt/mysql-client/lib/pkgconfig"
```
*Note: The activation command for virtual environments on macOS/Linux is `source venv/bin/activate`.*

### Database Credentials
The application connects to MySQL using the following default credentials (configured in `.env`):

| Variable | Value |
| :--- | :--- |
| **DB_NAME** | `weave_db` |
| **DB_USER** | `root` |
| **DB_PASSWORD** | `1234` |
| **DB_HOST** | `127.0.0.1` |
| **DB_PORT** | `3306` |

### Default Admin Credentials
After initializing the database (see Backend Step 4), you can log in with the following system administrator account:

| Field | Value |
| :--- | :--- |
| **Email** | `admin@weaveforward.com` |
| **Password** | `SecureAdminPassword123` |

---

## Backend Execution Procedures

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

4. **Initialize the Database**:
   Execute the database initialization script to automate the creation of the MySQL schema and seed the initial administrator account:
   ```powershell
   python manage.py bootstrap_environment
   ```

5. **Apply Database Migrations**:
   ```powershell
   python manage.py migrate
   ```

6. **Start the Backend Server**:
   ```powershell
   python manage.py runserver 127.0.0.1:8000
   ```
   *The backend will be accessible at `http://127.0.0.1:8000/`.*

---

## Frontend Execution Procedures

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

4. **Apply Database Migrations**:
   ```powershell
   python manage.py migrate
   ```

5. **Start the Frontend Server**:
   ```powershell
   python manage.py runserver 8001
   ```
   *The frontend will be accessible at `http://127.0.0.1:8001/`.*

> [!NOTE]
> The frontend is powered by **Daphne ASGI** (integrated directly into the Django development server). This allows it to natively support async middleware and asynchronous backend proxy calls without locking files on Windows during local development.

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
- [ ] Django SQL to Google Cloud Storage + BigQuery + Cloud Run + Scheduler + Database Migrations Set-Up
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
- [ ] TUAB Features Blackbox Selenium Test Script

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

- [ ] Full System Dry Run #1 (with Capstone Adviser)
- [ ] Revisions #1
- [ ] Full System Dry Run #2 (internal)
- [ ] Revisions #2
- [ ] UAT GForm & Interview - Donor
- [ ] UAT GForm & Interview - TUAB

---

## Troubleshooting and Maintenance

### Database Connection Issues (Backend)
If the backend application fails to connect to MySQL, verify that the MySQL service is active and that the credentials in `WeaveForward_Backend/.env` match your local configuration.

---

## Webhook & ngrok Configuration

For local development of features requiring external callbacks (like Maya payment processing), the backend uses an ngrok tunnel to expose the local server to the internet.

*   **Static ngrok Link**: `https://raquel-washiest-heike.ngrok-free.dev/api/webhooks/`
    *   *Note: This link is static as it uses a free-tier permanent domain.*
*   **How to Use**:
    1.  Ensure your backend is running on port `8000`.
    2.  Start ngrok with the static domain:
        ```powershell
        ngrok http --domain=raquel-washiest-heike.ngrok-free.dev 8000
        ```
    3.  Maya webhooks will now be forwarded to your local instance.
