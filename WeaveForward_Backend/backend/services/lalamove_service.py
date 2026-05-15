import hmac
import hashlib
import json
import time
import uuid
import requests
from django.conf import settings

def get_lalamove_quotation(pickup_lat, pickup_lng, pickup_address, dropoff_lat, dropoff_lng, dropoff_address, schedule_at):
    """
    Fetches a delivery quotation from Lalamove API.
    """
    api_key = settings.LALAMOVE_API_KEY
    api_secret = settings.LALAMOVE_API_SECRET
    base_url = "https://rest.sandbox.lalamove.com"
    path = "/v3/quotations"
    
    # Ensure coordinates are formatted to 7 decimal places as requested
    formatted_pickup_lat = "{:.7f}".format(float(pickup_lat))
    formatted_pickup_lng = "{:.7f}".format(float(pickup_lng))
    formatted_dropoff_lat = "{:.7f}".format(float(dropoff_lat))
    formatted_dropoff_lng = "{:.7f}".format(float(dropoff_lng))

    data = {
        "data": {
            "scheduleAt": schedule_at,
            "serviceType": "SEDAN",
            "language": "en_PH",
            "stops": [
                {
                    "coordinates": {
                        "lat": formatted_pickup_lat,
                        "lng": formatted_pickup_lng
                    },
                    "address": pickup_address
                },
                {
                    "coordinates": {
                        "lat": formatted_dropoff_lat,
                        "lng": formatted_dropoff_lng
                    },
                    "address": dropoff_address
                }
            ]
        }
    }
    
    timestamp = str(int(time.time() * 1000))
    method = "POST"
    # Using separators=(',', ':') to match CryptoJS behavior (no extra spaces)
    body = json.dumps(data, separators=(',', ':'))
    
    signature_payload = f"{timestamp}\r\n{method}\r\n{path}\r\n\r\n{body}"
    signature = hmac.new(
        api_secret.encode('utf-8'),
        signature_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "Authorization": f"hmac {api_key}:{timestamp}:{signature}",
        "Market": "PH",
        "Request-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    response = requests.post(f"{base_url}{path}", headers=headers, data=body)
    
    if response.status_code != 201 and response.status_code != 200:
        return {"error": response.json(), "status_code": response.status_code}
        
    return response.json()
