import requests
import json

BASE_URL = "http://127.0.0.1:8000/api"
EMAIL = "admin@weaveforward.com"
PASSWORD = "SecureAdminPassword123"

def test_response():
    try:
        session = requests.Session()
        
        # 1. Login to get cookies
        print(f"Logging in as {EMAIL}...")
        login_res = session.post(f"{BASE_URL}/login", json={"email": EMAIL, "password": PASSWORD})
        
        if login_res.status_code != 200:
            print(f"Login failed: {login_res.status_code}")
            print(login_res.text)
            return
        
        print("Login successful. Cookies captured.")
        
        # 2. Fetch donations (cookies are handled by session)
        print(f"Fetching donations from {BASE_URL}/donations...")
        response = session.get(f"{BASE_URL}/donations")
        
        if response.status_code == 200:
            data = response.json()
            items = data.get('results', []) if isinstance(data, dict) else data
            
            if items:
                print("\n--- SAMPLE DONATION RESPONSE (FORMATTED) ---")
                # Find a donation that has items to show the effect
                sample = next((d for d in items if d.get('items')), items[0])
                
                output = {
                    "donation_id": sample.get("donation_id"),
                    "status": sample.get("status"),
                    "items": []
                }
                for itm in sample.get("items", []):
                    lookup = itm.get("lookup_details", {})
                    output["items"].append({
                        "item_id": itm.get("item_id"),
                        "condition": itm.get("condition_rating"),
                        "material_info": {
                            "category": lookup.get("category"),
                            "brand": lookup.get("brand"),
                            "clothing_type": lookup.get("clothing_type"),
                            "fiber_json": lookup.get("fiber_json"),
                        }
                    })
                
                print(json.dumps(output, indent=2))
            else:
                print("No donations found.")
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_response()
