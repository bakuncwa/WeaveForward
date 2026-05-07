import MySQLdb
import os
import sys
import subprocess
from dotenv import load_dotenv

# Setup Django environment for ORM access
def setup_django():
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'WeaveForward_Backend.settings')
    django.setup()

def seed_admins():
    from backend.models import User, UserRole
    # ==============================================================================
    # HARDCODED ADMINS
    # ==============================================================================
    admins = [
        {
            "email": "admin@weaveforward.com",
            "password": "SecureAdminPassword123",
            "first_name": "System",
            "last_name": "Admin",
            "contact_no": "+639000000000"
        }
    ]
    
    for admin_data in admins:
        user = User.objects.filter(email=admin_data["email"]).first()
        if not user:
            User.objects.create_superuser(
                email=admin_data["email"],
                password=admin_data["password"],
                first_name=admin_data["first_name"],
                last_name=admin_data["last_name"],
                contact_no=admin_data["contact_no"]
            )
            print(f"[OK] Created admin: {admin_data['email']}")
        else:
            # Update password for existing admin to ensure it's always valid
            user.set_password(admin_data["password"])
            user.save()
            print(f"[OK] Updated existing admin: {admin_data['email']}")

def main():
    load_dotenv()
    
    db_name = os.getenv('DB_NAME')
    db_user = os.getenv('DB_USER', 'root')
    db_password = os.getenv('DB_PASSWORD', '')
    db_host = os.getenv('DB_HOST', '127.0.0.1')
    db_port = int(os.getenv('DB_PORT', 3306))
    instance_connection_name = os.getenv('CLOUD_SQL_CONNECTION_NAME')

    if not db_name:
        print("[ERROR] DB_NAME not found in environment.")
        sys.exit(1)

    # 1. Ensure Database Exists
    try:
        if instance_connection_name:
            print(f"[CONNECT] Connecting via Cloud SQL Socket: /cloudsql/{instance_connection_name}...")
            conn = MySQLdb.connect(user=db_user, passwd=db_password, unix_socket=f'/cloudsql/{instance_connection_name}')
        else:
            print(f"[CONNECT] Connecting to local MySQL at {db_host}:{db_port}...")
            conn = MySQLdb.connect(host=db_host, user=db_user, passwd=db_password, port=db_port)
        
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
        print(f"[OK] Database '{db_name}' is ready.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Database Creation Error: {e}")
        # We don't exit here because on GCP the DB might already exist and user might not have CREATE permissions
        print("Attempting to proceed with migrations anyway...")

    # 2. Run Migrations
    print("[MIGRATE] Running migrations...")
    try:
        subprocess.run([sys.executable, "manage.py", "migrate"], check=True)
    except subprocess.CalledProcessError:
        print("[ERROR] Migration failed.")
        sys.exit(1)

    # 3. Seed Admins
    print("[SEED] Seeding admin accounts...")
    try:
        setup_django()
        seed_admins()
    except Exception as e:
        print(f"[ERROR] Seeding Error: {e}")
        sys.exit(1)

    # 4. Populate Product Catalog
    print("[CATALOG] Populating product catalog...")
    try:
        subprocess.run([sys.executable, "manage.py", "populate_catalog"], check=True)
    except subprocess.CalledProcessError:
        print("[ERROR] Catalog population failed.")
        sys.exit(1)

    print("\nInitialization complete!")

if __name__ == "__main__":
    main()
