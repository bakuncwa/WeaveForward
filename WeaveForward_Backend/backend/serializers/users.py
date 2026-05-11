import os
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
import pyotp
import re
from rest_framework import serializers

from ..models import SubscriptionStatus, Upload, User, UserRole
from ..services.upload_service import build_upload_url
from ..services.location_service import get_city_and_barangay
from ..services.brand_fiber_lookup_service import get_allowed_fibers


class UserSerializer(serializers.ModelSerializer):
    """Full user profile serializer."""
    is_subscribed = serializers.SerializerMethodField(read_only=True)
    latitude = serializers.DecimalField(max_digits=18, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=18, decimal_places=7, required=False, allow_null=True)
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)
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
            'maya_card_id', 'status', 'is_2fa_enabled', 'is_subscribed', 'upload', 'documentation',
            'created_at', 'updated_at'
        ]

    def get_is_subscribed(self, obj):
        annotated_value = getattr(obj, 'is_subscribed', None)
        if annotated_value is not None:
            return bool(annotated_value)
        return obj.subscriptions.filter(status=SubscriptionStatus.ACTIVE).exists()

    def validate_password(self, value):
        if len(value) < 8 or not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise serializers.ValidationError(
                "Password must be at least 8 characters and contain both letters and numbers."
            )
        return value

    def validate_upload(self, v):
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

        # 2. Role-specific validation
        # Use instance role if updating, otherwise use role from data
        effective_role = instance.role if instance else data.get('role')

        if effective_role == UserRole.DONOR:
            # Strict Whitelist for Donor
            allowed_donor_fields = {
                'first_name', 'middle_name', 'last_name', 'contact_no',
                'display_address', 'latitude', 'longitude', 'password',
                'upload'
            }
            if instance:
                incoming_fields = set(self.initial_data.keys())
                unauthorized = sorted(incoming_fields - allowed_donor_fields - self.blocked_patch_fields)
                for f in unauthorized:
                    errors[f] = "This field cannot be updated for Donor users."

            for f in ['first_name', 'last_name', 'contact_no', 'display_address', 'latitude', 'longitude']:
                if f in data:
                    if data[f] is None or not str(data[f]).strip():
                        errors[f] = "This field may not be blank."
                elif not instance:
                    errors[f] = "This field is required."

        # 3. TUAB mandatory & whitelist fields
        if effective_role == UserRole.TUAB:
            # Strict Whitelist: Only fields present in admin_edit_tuab.html
            allowed_tuab_fields = {
                'business_name', 'description',
                'social_link', 'contact_no', 'max_active_claims', 'max_distance_km',
                'min_biodeg_score', 'operational_status', 'target_fibers', 'latitude',
                'longitude', 'display_address', 'password', 'upload'
            }
            if instance:
                incoming_fields = set(self.initial_data.keys())
                unauthorized = sorted(incoming_fields - allowed_tuab_fields - self.blocked_patch_fields)
                for f in unauthorized:
                    errors[f] = "This field cannot be updated for TUAB users."

            # Mandatory fields for TUAB
            tuab_mandatory = [
                'business_name', 'description', 'social_link', 'contact_no',
                'max_active_claims', 'max_distance_km', 'min_biodeg_score', 'target_fibers'
            ]
            for f in tuab_mandatory:
                if f in data:
                    val = data[f]
                    if val is None or (isinstance(val, str) and not val.strip()):
                        errors[f] = "This field may not be blank for TUAB."
                elif not instance:
                    errors[f] = "This field is required for TUAB."

            # Dynamic Fiber Validation
            target_fibers = data.get('target_fibers')
            if target_fibers:
                # Clean input: strictly lowercase, no spaces
                fibers = [f.strip().lower() for f in target_fibers.split(',') if f.strip()]
                data['target_fibers'] = ','.join(fibers)
                
                db_fibers = get_allowed_fibers()
                invalid = [f for f in fibers if f not in db_fibers]
                if invalid:
                    errors['target_fibers'] = f"Invalid fibers (not in our database): {', '.join(invalid)}"

        if errors: raise serializers.ValidationError(errors)

        # 4. Location Lookup & Coordinate Formatting
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
        upload_file = validated_data.pop('upload', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        if upload_file:
            # Minification/Optimization
            try:
                img = Image.open(upload_file)
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
                optimized_filename = f"{os.path.splitext(upload_file.name)[0]}.jpg"
                optimized_file = ContentFile(buffer.read(), name=optimized_filename)
                
                stored_path = default_storage.save(f"profile_photos/{optimized_filename}", optimized_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(optimized_filename)[:50]
                )
            except Exception as e:
                # Fallback to original if processing fails
                stored_path = default_storage.save(f"profile_photos/{upload_file.name}", upload_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(upload_file.name)[:50]
                )

        instance.save()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['upload'] = build_upload_url(instance.upload, self.context)
        data['documentation'] = build_upload_url(instance.documentation, self.context)
        data.pop('password', None)
        return data


class PublicUserSerializer(serializers.ModelSerializer):
    """Limited profile serializer for non-admin views."""
    latitude = serializers.DecimalField(max_digits=18, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=18, decimal_places=7, required=False, allow_null=True)
    upload = serializers.SerializerMethodField()

    class Meta:
        model = User
        exclude = [
            'password', 'totp_secret', 'maya_customer_id', 'maya_card_id',
            'is_2fa_enabled', 'created_at', 'updated_at', 'documentation'
        ]

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


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
