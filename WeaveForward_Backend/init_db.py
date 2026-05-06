import MySQLdb
import os
import sys
from dotenv import load_dotenv

def main():
    # Load environment variables from .env file
    load_dotenv()
    
    db_name = os.getenv('DB_NAME')
    db_user = os.getenv('DB_USER', 'root')
    db_password = os.getenv('DB_PASSWORD', '')
    db_host = os.getenv('DB_HOST', '127.0.0.1')
    db_port = int(os.getenv('DB_PORT', 3306))
    
    # GCP Cloud SQL specific: Connection Name (e.g., project:region:instance)
    instance_connection_name = os.getenv('CLOUD_SQL_CONNECTION_NAME')

    if not db_name:
        print("Error: DB_NAME not found in environment variables.")
        sys.exit(1)

    try:
        if instance_connection_name:
            # GCP/Cloud Run Connection via Unix Socket
            print(f"Checking database '{db_name}' via Cloud SQL Socket: /cloudsql/{instance_connection_name}...")
            conn = MySQLdb.connect(
                user=db_user,
                passwd=db_password,
                unix_socket=f'/cloudsql/{instance_connection_name}'
            )
        else:
            # Local/TCP Connection
            print(f"Checking database '{db_name}' at {db_host}:{db_port}...")
            conn = MySQLdb.connect(
                host=db_host,
                user=db_user,
                passwd=db_password,
                port=db_port
            )
        
        cursor = conn.cursor()
        
        # Create database if it doesn't exist
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
        
        print(f"Successfully ensured database '{db_name}' exists.")
        
        cursor.close()
        conn.close()
    except MySQLdb.Error as e:
        print(f"MySQL Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
