import os

# Environment-based settings
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8001")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

# Registration Constants
ALLOWED_FIBERS = {
    'cotton', 'polyester', 'nylon', 'wool', 'linen', 'silk', 'rayon', 
    'viscose', 'acrylic', 'elastane', 'spandex', 'lycra', 'modal', 
    'bamboo', 'hemp', 'denim', 'cashmere', 'tencel', 'lyocell', 'alpaca'
}

# TUAB Registration Specific
TUAB_REG_ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf'}
TUAB_REG_MAX_SIZE = 50 * 1024 * 1024  # 50MB

# General File Upload Constants
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
IMAGE_COMPRESSION_QUALITY = 70
