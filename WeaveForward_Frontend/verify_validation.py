import requests
import json

BASE_URL = "http://127.0.0.1:8000/api"
EMAIL = "admin@weaveforward.com"
PASSWORD = "SecureAdminPassword123"

def test_validations():
    try:
        session = requests.Session()
        session.post(f"{BASE_URL}/login", json={"email": EMAIL, "password": PASSWORD})
        csrf_token = session.cookies.get('csrftoken')
        headers = {"X-CSRFToken": csrf_token, "Referer": "http://127.0.0.1:8000"}
        
        # 1. Test Location (Outside NCR) - Use valid 7 decimals
        payload = {
            "donor_user_id": 2, # Assuming 2 is a donor
            "items": json.dumps([{"lookup_id": 10168, "weight_kg": 1.5, "condition_rating": "Good"}]),
            "preferred_pickup_date": "2026-05-20T10:00:00Z",
            "preferred_pickup_window_start": "09:00:00",
            "preferred_pickup_window_end": "12:00:00",
            "pickup_display_address": "Ocean",
            "pickup_latitude": "0.0000000",
            "pickup_longitude": "0.0000000"
        }
        
        print("Testing Location (0.0000000)...")
        res = session.post(f"{BASE_URL}/donations", data=payload, headers=headers)
        print(f"Status: {res.status_code}")
        print(json.dumps(res.json(), indent=2))
        
        # 2. Test Time Window (End < Start)
        payload["pickup_latitude"] = "14.5995000" # Manila
        payload["pickup_longitude"] = "120.9842000"
        payload["preferred_pickup_window_start"] = "15:00:00"
        payload["preferred_pickup_window_end"] = "10:00:00"
        
        print("\nTesting Time Window (15:00 to 10:00)...")
        res = session.post(f"{BASE_URL}/donations", data=payload, headers=headers)
        print(f"Status: {res.status_code}")
        print(json.dumps(res.json(), indent=2))

    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_validations()
