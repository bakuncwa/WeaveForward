import re, os, io
from rest_framework import serializers
from .models import User, Upload
from .constants import ALLOWED_FIBERS, TUAB_REG_MAX_SIZE, TUAB_REG_ALLOWED_EXTENSIONS, ALLOWED_IMAGE_EXTENSIONS, IMAGE_COMPRESSION_QUALITY
from .services.location_service import get_city_and_barangay
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from PIL import Image

class DonorRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    phone = serializers.CharField(source='contact_no')
    pickup_address = serializers.CharField(source='display_address')
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7)

    class Meta:
        model = User
        fields = [
            'first_name', 'middle_name', 'last_name', 'email', 
            'phone', 'password', 'confirm_password', 
            'pickup_address', 'latitude', 'longitude'
        ]

    def validate(self, data):
        # 1. Password confirmation
        if data.get('password') != data.get('confirm_password'):
            raise serializers.ValidationError({"password": "Passwords do not match."})

        # 2. Phone validation (+63 prefix, 13 chars)
        if not re.match(r'^\+63\d{10}$', data.get('contact_no', '')):
            raise serializers.ValidationError({"phone": "Phone must be +63 followed by 10 digits."})

        # 3. Coordinate precision check (exactly 7 decimals)
        raw_lat, raw_lng = str(self.initial_data.get('latitude', '')), str(self.initial_data.get('longitude', ''))
        if '.' not in raw_lat or len(raw_lat.split('.')[-1]) != 7 or '.' not in raw_lng or len(raw_lng.split('.')[-1]) != 7:
            raise serializers.ValidationError({"location": "Coordinates must be sent with exactly 7 decimal places."})

        # 4. NCR (Metro Manila) Geofence Check
        loc = get_city_and_barangay(data.get('latitude'), data.get('longitude'))
        if not loc:
            raise serializers.ValidationError({"location": "Location must be within Metro Manila (NCR)."})

        # 5. Internal data population
        data['city'], data['barangay'] = loc['city'], loc['barangay']
        return data

    def create(self, validated_data):
        # Setup role and active status for Donors
        role, password = validated_data.pop('role', 'Donor'), validated_data.pop('password')
        validated_data.pop('confirm_password', None)
        validated_data['role'], validated_data['status'] = role, 'ACTIVE'
        return User.objects.create_user(password=password, **validated_data)

class TUABRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    biz_name = serializers.CharField(source='business_name')
    phone = serializers.CharField(source='contact_no')
    address = serializers.CharField(source='display_address')
    lat = serializers.DecimalField(source='latitude', max_digits=10, decimal_places=7)
    lng = serializers.DecimalField(source='longitude', max_digits=10, decimal_places=7)
    desc = serializers.CharField(source='description', required=False)
    social = serializers.URLField(source='social_link', required=False)
    fibers = serializers.CharField(source='target_fibers')
    max_dist = serializers.DecimalField(source='max_distance_km', max_digits=5, decimal_places=2)
    min_biodegradability = serializers.DecimalField(source='min_biodeg_score', max_digits=3, decimal_places=2)
    auth_file = serializers.FileField(source='documentation', required=False)

    class Meta:
        model = User
        fields = [
            'biz_name', 'email', 'phone', 'password', 'confirm_password',
            'desc', 'social', 'address', 'lat', 'lng',
            'fibers', 'max_dist', 'min_biodegradability', 'auth_file'
        ]

    def validate(self, data):
        # 1. Password confirmation
        if data.get('password') != data.get('confirm_password'):
            raise serializers.ValidationError({"password": "Passwords do not match."})

        # 2. Phone validation
        if not re.match(r'^\+63\d{10}$', data.get('contact_no', '')):
            raise serializers.ValidationError({"phone": "Phone must be +63 followed by 10 digits."})
        
        # 3. File validation (TUAB Specific Extensions & Size)
        auth_file = self.initial_data.get('auth_file')
        if auth_file:
            ext = os.path.splitext(auth_file.name)[1].lower()
            if ext not in TUAB_REG_ALLOWED_EXTENSIONS:
                raise serializers.ValidationError({"auth_file": f"Only {', '.join(TUAB_REG_ALLOWED_EXTENSIONS)} files are allowed for registration."})
            if hasattr(auth_file, 'size') and auth_file.size > TUAB_REG_MAX_SIZE:
                raise serializers.ValidationError({"auth_file": f"File size must be under {TUAB_REG_MAX_SIZE // (1024*1024)}MB."})

        # 4. Strict Fiber Format and Whitelist Validation
        raw_fibers = data.get('target_fibers', '')
        if ' ' in raw_fibers or any(c.isupper() for c in raw_fibers):
            raise serializers.ValidationError({"fibers": "Fibers must be strictly lowercase and comma-separated with no spaces."})
        
        input_fibers = [f for f in raw_fibers.split(',') if f]
        invalid = [f for f in input_fibers if f not in ALLOWED_FIBERS]
        if invalid: raise serializers.ValidationError({"fibers": f"Invalid fibers: {', '.join(invalid)}"})
        data['target_fibers'] = raw_fibers

        # 5. Coordinate precision check
        raw_lat, raw_lng = str(self.initial_data.get('lat', '')), str(self.initial_data.get('lng', ''))
        if '.' not in raw_lat or len(raw_lat.split('.')[-1]) != 7 or '.' not in raw_lng or len(raw_lng.split('.')[-1]) != 7:
            raise serializers.ValidationError({"location": "Coordinates must be sent with exactly 7 decimal places."})
        
        # 6. NCR Lookup
        loc = get_city_and_barangay(data.get('latitude'), data.get('longitude'))
        if not loc:
            raise serializers.ValidationError({"location": "Location must be within Metro Manila (NCR)."})
        data['city'], data['barangay'] = loc['city'], loc['barangay']
        
        return data

    def create(self, validated_data):
        auth_file = validated_data.pop('documentation', None)
        role, password = validated_data.pop('role', 'TUAB'), validated_data.pop('password')
        validated_data.pop('confirm_password', None)
        validated_data['role'], validated_data['status'] = role, 'UNDER_REVIEW'

        # Process and Minify image files
        if auth_file:
            ext = os.path.splitext(auth_file.name)[1].lower()
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                img = Image.open(auth_file)
                if img.mode != 'RGB': img = img.convert('RGB')
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=IMAGE_COMPRESSION_QUALITY, optimize=True)
                auth_file = ContentFile(buffer.getvalue(), name=os.path.splitext(auth_file.name)[0] + ".jpg")
            
            path = default_storage.save(f'documentation/{auth_file.name}', auth_file)
            validated_data['documentation'] = Upload.objects.create(file_path=path, name=auth_file.name)

        return User.objects.create_user(password=password, **validated_data)
