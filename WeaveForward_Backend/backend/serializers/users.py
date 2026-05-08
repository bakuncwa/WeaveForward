import os
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
import pyotp
import re
from rest_framework import serializers

from ..models import Upload, User, UserRole
from ..services.location_service import get_city_and_barangay


class UploadSerializer(serializers.ModelSerializer):
    """Full metadata for uploaded files with absolute URLs."""
    file_path = serializers.SerializerMethodField()

    class Meta:
        model = Upload
        fields = ['upload_id', 'file_path', 'name']

    def get_file_path(self, obj):
        if not obj.file_path:
            return None
        url = default_storage.url(obj.file_path)
        if url.startswith(('http://', 'https://')):
            return url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class UserSerializer(serializers.ModelSerializer):
    """Full user profile serializer."""
    upload = serializers.PrimaryKeyRelatedField(queryset=Upload.objects.all(), required=False, allow_null=True)
    profile_picture = serializers.FileField(write_only=True, required=False, allow_null=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    blocked_patch_fields = {
        'email', 'user_id', 'city', 'barangay', 'role',
        'maya_customer_id', 'maya_card_id', 'is_2fa_enabled',
        'documentation', 'status', 'created_at', 'updated_at'
    }

    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'password', 'role', 'first_name', 'last_name', 'middle_name',
            'business_name', 'description', 'social_link', 'max_active_claims', 'target_fibers',
            'min_biodeg_score', 'max_distance_km', 'operational_status', 'contact_no',
            'barangay', 'city', 'latitude', 'longitude', 'display_address', 'maya_customer_id',
            'maya_card_id', 'status', 'is_2fa_enabled', 'upload', 'profile_picture', 'documentation',
            'created_at', 'updated_at'
        ]

    def validate_password(self, value):
        if len(value) < 8 or not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise serializers.ValidationError(
                "Password must be at least 8 characters and contain both letters and numbers."
            )
        return value

    def validate_profile_picture(self, v):
        if v:
            if v.size > 5242880: raise serializers.ValidationError("Image too large (max 5MB).")
            if not v.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                raise serializers.ValidationError("Invalid format (only JPG, JPEG, PNG allowed).")
        return v

    def validate(self, data):
        instance = getattr(self, 'instance', None)
        errors = {}

        # 1. Blocked fields
        if instance:
            blocked = sorted(self.blocked_patch_fields.intersection(self.initial_data.keys()))
            for f in blocked: errors[f] = "This field cannot be updated through this endpoint."

        # 2. Donor mandatory fields
        role = data.get('role', instance.role if instance else None)
        if role == UserRole.DONOR:
            for f in ['first_name', 'last_name', 'contact_no', 'display_address', 'latitude', 'longitude']:
                if f in data:
                    if data[f] is None or not str(data[f]).strip():
                        errors[f] = "This field may not be blank."
                elif not instance:
                    errors[f] = "This field is required."

        if errors: raise serializers.ValidationError(errors)

        # 3. Location Lookup & Coordinate Formatting
        lat, lng = data.get('latitude'), data.get('longitude')
        if lat is not None or lng is not None:
            latitude, longitude = lat or (instance.latitude if instance else None), lng or (instance.longitude if instance else None)
            
            # Ensure coordinates are formatted to 7 decimal places
            if 'latitude' in data: data['latitude'] = round(float(data['latitude']), 7)
            if 'longitude' in data: data['longitude'] = round(float(data['longitude']), 7)

            if not (loc := get_city_and_barangay(latitude, longitude)):
                raise serializers.ValidationError({"location": "Location must be within Metro Manila (NCR)."})
            data.update({'city': loc['city'], 'barangay': loc['barangay']})
            
        # 4. Phone format (Universal)
        if 'contact_no' in data and data['contact_no']:
            if not re.match(r'^\+63\d{10}$', data['contact_no']):
                raise serializers.ValidationError({"contact_no": "Phone must be +63 followed by 10 digits."})

        return data

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        profile_picture = validated_data.pop('profile_picture', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        if profile_picture:
            # Minification/Optimization
            try:
                img = Image.open(profile_picture)
                # Convert to RGB if necessary (e.g. for RGBA PNGs being saved as JPEG)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Resize to max 300x300 while maintaining aspect ratio
                img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                
                # Save optimized version to buffer
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)
                
                # Create a new Django-compatible content file
                optimized_filename = f"{os.path.splitext(profile_picture.name)[0]}.jpg"
                optimized_file = ContentFile(buffer.read(), name=optimized_filename)
                
                stored_path = default_storage.save(f"profile_photos/{optimized_filename}", optimized_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(optimized_filename)[:50]
                )
            except Exception as e:
                # Fallback to original if processing fails
                stored_path = default_storage.save(f"profile_photos/{profile_picture.name}", profile_picture)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(profile_picture.name)[:50]
                )

        instance.save()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['upload'] = UploadSerializer(instance.upload, context=self.context).data if instance.upload else None
        data.pop('password', None)
        return data


class PublicUserSerializer(serializers.ModelSerializer):
    """Limited profile serializer for non-admin views."""
    upload = UploadSerializer(read_only=True)

    class Meta:
        model = User
        exclude = [
            'password', 'totp_secret', 'maya_customer_id', 'maya_card_id',
            'is_2fa_enabled', 'created_at', 'updated_at', 'documentation'
        ]


class TwoFactorSerializer(serializers.Serializer):
    secret = serializers.CharField()
    otp_code = serializers.CharField()

    default_error_messages = {
        'invalid_otp': 'Invalid 2FA code.'
    }

    def validate(self, data):
        totp = pyotp.TOTP(data['secret'])
        if not totp.verify(data['otp_code']):
            raise serializers.ValidationError({"detail": self.error_messages['invalid_otp']})
        return data
