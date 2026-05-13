# WeaveForward

Improved ML Repository (Forked): https://github.com/dave34458/weaveforward-ml
Mock HTML Files: https://github.com/dave34458/WeaveForward-Mock-HTML-Files


## Architecture & Security Specifications
This project adheres to formal proposal specifications, featuring a **physically decoupled 3-tier native GCP architecture**. It is engineered for high availability and scalability, ready for deployment using **Cloud SQL** and dual **Cloud Run** instances for independent service orchestration.

### Core Technical Standards
- **Security & Authentication**: Implements industry-standard `bcrypt` password hashing and `simple-jwt` (JSON Web Tokens) for secure, stateless authentication.
- **Hardened Defense**: Built-in security specifications to mitigate **CORS**, **CSS**, and **XSS** vulnerabilities, ensuring robust protection across all application layers.
- **Cloud-Native Design**: Architected for seamless integration with Google Cloud Platform services, facilitating a production-ready environment.

## Project Completion Status
**Overall Progress: ~62%**

Core infrastructure (JWT, 3-tier, Admin) and key integrations (**Maya Payments** & **CatBoost ML**) are fully operational. Final development is focused on **Lalamove integration**, TUAB workflows, and impact dashboards.

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

> [!IMPORTANT]
> Ensure your local MySQL `root` user has the password set to `1234` or update the `.env` file to match your configuration.

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
