# WeaveForward

WeaveForward is a sustainable fashion platform designed to connect donors with Textile Upcycling and Aggregation Businesses (TUABs). This repository contains the full application stack, including the Django Backend and the Django-based Frontend.

## Getting Started

To ensure cross-platform compatibility and avoid path-related errors, this repository includes the environment configuration (`.env`) but requires you to initialize your own local virtual environment.

### Prerequisites
* **Python 3.12**: Ensure Python 3.12 is installed on your system.
* **MySQL Server**: A local MySQL instance must be running for the Backend.
* **Database Credentials**: The included `.env` expects a MySQL `root` user with the password `1234`.

---

## Backend Execution Procedures

1. **Navigate to the Backend Directory**:
   ```powershell
   cd WeaveForward_Backend
   ```

2. **Initialize and Activate Virtual Environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Initialize the Database**:
   Execute the database initialization script to automate the creation of the required MySQL schema:
   ```powershell
   python init_db.py
   ```

5. **Apply Database Migrations**:
   ```powershell
   python manage.py migrate
   ```

6. **Start the Development Server**:
   ```powershell
   python manage.py runserver
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
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Apply Database Migrations**:
   ```powershell
   python manage.py migrate
   ```

5. **Start the Development Server**:
   ```powershell
   python manage.py runserver 8001
   ```
   *The frontend will be accessible at `http://127.0.0.1:8001/`.*

---

## Troubleshooting and Maintenance

### Database Connection Issues (Backend)
If the backend application fails to connect to MySQL, verify that the MySQL service is active and that the credentials in `WeaveForward_Backend/.env` match your local configuration.

---

## Deployment Configuration
The application architecture supports hybrid deployment for Google Cloud Platform (GCP). For production deployment:
1. Locate the **BLOCK 2** settings in the `.env` files.
2. Uncomment the production-specific variables (Cloud SQL, GCS, etc.).
3. Configure the GCP environment according to the project's Cloud Run and Cloud SQL specifications.
