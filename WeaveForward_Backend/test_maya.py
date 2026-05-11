import os
import django
import json

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'WeaveForward_Backend.settings')
django.setup()

from backend.services.subscription_service import subscribe_user

data = {
  "firstName": "Joshua",
  "lastName": "Vinson",
  "card": {
    "number": "5123456789012346",
    "expMonth": "12",
    "expYear": "2030",
    "cvc": "111"
  }
}

result = subscribe_user(
    target_user_id=3,
    first_name=data['firstName'],
    last_name=data['lastName'],
    card=data['card']
)
print(json.dumps(result))
