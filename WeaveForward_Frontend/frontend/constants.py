import os

# Base Backend URL
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000/api")

TEXT_FIELD_MAX_LENGTH = 1000

# Strict Fiber Whitelist (Must match backend/constants.py)
ALLOWED_FIBERS = [
    'cotton', 'polyester', 'nylon', 'wool', 'linen', 'silk', 'rayon', 
    'viscose', 'acrylic', 'elastane', 'spandex', 'lycra', 'modal', 
    'bamboo', 'hemp', 'denim', 'cashmere', 'tencel', 'lyocell', 'alpaca'
]
