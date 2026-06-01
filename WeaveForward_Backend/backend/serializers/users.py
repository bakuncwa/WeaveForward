import os
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
import pyotp
import uuid
import re
from rest_framework import serializers

from ..constants import TEXT_FIELD_MAX_LENGTH
from ..models import Donation, DonationStatus, SubscriptionStatus, Upload, User, UserRole
from ..services.etag_service import build_updated_at_etag
from ..services.upload_service import build_upload_url
from ..services.location_service import get_city_and_barangay
from ..services.brand_fiber_lookup_service import get_allowed_fibers


class AdminUserDetailSerializer(serializers.ModelSerializer):
    """Full user profile serializer used exclusively by Admins for viewing details."""
    is_subscribed = serializers.SerializerMethodField(read_only=True)
    total_donations = serializers.SerializerMethodField(read_only=True)
    etag = serializers.SerializerMethodField(read_only=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, max_length=User._meta.get_field('password').max_length)
    distance_km = serializers.FloatField(read_only=True, required=False)
    blocked_patch_fields = {
        'email', 'user_id', 'city', 'barangay', 'role',
        'is_2fa_enabled',
        'documentation', 'status', 'created_at', 'updated_at'
    }

    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'password', 'role', 'first_name', 'last_name', 'middle_name',
            'business_name', 'description', 'social_link', 'max_active_claims', 'target_fibers',
            'min_biodeg_score', 'max_distance_km', 'operational_status', 'contact_no',
            'barangay', 'city', 'latitude', 'longitude', 'display_address',
            'status', 'is_2fa_enabled', 'is_subscribed', 'total_donations', 'upload', 'documentation',
            'created_at', 'updated_at', 'etag', 'distance_km'
        ]

    def get_is_subscribed(self, obj):
        annotated_value = getattr(obj, 'is_subscribed', None)
        if annotated_value is not None:
            return bool(annotated_value)
        return obj.subscriptions.filter(status=SubscriptionStatus.ACTIVE).exists()

    def get_total_donations(self, obj):
        return Donation.objects.filter(
            claimed_by_tuab_id=obj.user_id,
            status=DonationStatus.RECEIVED,
        ).count()

    def get_etag(self, obj):
        return build_updated_at_etag(obj)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['upload'] = build_upload_url(instance.upload, self.context)
        data['documentation'] = build_upload_url(instance.documentation, self.context)
        data.pop('password', None)

        # Dynamic role-based field exclusion
        if instance.role == UserRole.DONOR:
            donor_removals = [
                'business_name', 'description', 'social_link', 'max_active_claims', 
                'target_fibers', 'min_biodeg_score', 'max_distance_km', 
                'operational_status', 'documentation', 'total_donations',
            ]
            for field in donor_removals:
                data.pop(field, None)
        
        elif instance.role == UserRole.TUAB:
            tuab_removals = ['first_name', 'last_name', 'middle_name']
            for field in tuab_removals:
                data.pop(field, None)
        else:
            data.pop('total_donations', None)

        return data


class DonorSelfSerializer(serializers.ModelSerializer):
    """Dedicated serializer for donor self-profile pages."""
    etag = serializers.SerializerMethodField(read_only=True)
    upload = serializers.SerializerMethodField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'role', 'first_name', 'last_name', 'middle_name',
            'contact_no', 'barangay', 'city', 'latitude', 'longitude',
            'display_address', 'is_2fa_enabled', 'upload', 'created_at',
            'updated_at', 'etag'
        ]

    def get_etag(self, obj):
        return build_updated_at_etag(obj)

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


class DonorUpdateSerializer(serializers.ModelSerializer):
    """Dedicated serializer for donor profile updates."""
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, max_length=User._meta.get_field('password').max_length)

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'middle_name', 'contact_no',
            'display_address', 'latitude', 'longitude', 'password', 'upload',
            'city', 'barangay'
        ]
        read_only_fields = ['city', 'barangay']
        extra_kwargs = {
            'display_address': {'max_length': TEXT_FIELD_MAX_LENGTH},
        }



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

    def validate_first_name(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_last_name(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_display_address(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_contact_no(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        if not re.match(r'^\+63\d{10}$', value):
            raise serializers.ValidationError("Phone must be +63 followed by 10 digits.")
        return value

    def validate_latitude(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return round(float(value), 7)

    def validate_longitude(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return round(float(value), 7)

    def validate(self, data):
        errors = {}

        # Location formatting and checking (Cross-field validation)
        lat, lng = data.get('latitude'), data.get('longitude')
        instance = getattr(self, 'instance', None)
        if lat is not None or lng is not None:
            latitude = lat if lat is not None else (instance.latitude if instance else None)
            longitude = lng if lng is not None else (instance.longitude if instance else None)

            if not (loc := get_city_and_barangay(latitude, longitude)):
                errors["location"] = "Location must be within Metro Manila (NCR)."
            else:
                data.update({'city': loc['city'], 'barangay': loc['barangay']})

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        upload_file = validated_data.pop('upload', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        if upload_file:
            img = Image.open(upload_file)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=85, optimize=True)
            buffer.seek(0)
            
            optimized_filename = f"{uuid.uuid4().hex}.jpg"
            optimized_file = ContentFile(buffer.read(), name=optimized_filename)
            
            stored_path = default_storage.save(f"profile_photos/{optimized_filename}", optimized_file)
            instance.upload = Upload.objects.create(
                file_path=stored_path,
                name=os.path.basename(optimized_filename)
            )

        instance.save()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.upload:
            data['upload'] = build_upload_url(instance.upload, self.context)
        data.pop('password', None)
        return data


class TuabUpdateSerializer(serializers.ModelSerializer):
    """Dedicated serializer for TUAB profile updates."""
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, max_length=User._meta.get_field('password').max_length)

    class Meta:
        model = User
        fields = [
            'business_name', 'description', 'social_link', 'contact_no', 
            'max_active_claims', 'max_distance_km', 'min_biodeg_score', 
            'operational_status', 'target_fibers', 'latitude', 'longitude', 
            'display_address', 'password', 'upload', 'city', 'barangay'
        ]
        read_only_fields = ['city', 'barangay']
        extra_kwargs = {
            'description': {'max_length': TEXT_FIELD_MAX_LENGTH},
            'social_link': {'max_length': TEXT_FIELD_MAX_LENGTH},
            'target_fibers': {'max_length': TEXT_FIELD_MAX_LENGTH},
            'display_address': {'max_length': TEXT_FIELD_MAX_LENGTH},
        }

    def validate_password(self, value):
        if len(value) < 8 or not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise serializers.ValidationError("Password must be at least 8 characters and contain both letters and numbers.")
        return value

    def validate_upload(self, v):
        if v:
            if v.size > 5242880: raise serializers.ValidationError("Image too large (max 5MB).")
            if not v.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                raise serializers.ValidationError("Invalid format (only JPG, JPEG, PNG allowed).")
        return v

    def validate_business_name(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_description(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_social_link(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_contact_no(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        if not re.match(r'^\+63\d{10}$', value):
            raise serializers.ValidationError("Phone must be +63 followed by 10 digits.")
        return value

    def validate_display_address(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_max_active_claims(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_max_distance_km(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_min_biodeg_score(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_target_fibers(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        
        fibers = [f.strip().lower() for f in value.split(',') if f.strip()]
        db_fibers = get_allowed_fibers()
        invalid = [f for f in fibers if f not in db_fibers]
        if invalid:
            raise serializers.ValidationError(f"Invalid fibers (not in our database): {', '.join(invalid)}")
        return ','.join(fibers)

    def validate_latitude(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return round(float(value), 7)

    def validate_longitude(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return round(float(value), 7)

    def validate(self, data):
        errors = {}

        # Location formatting and checking (Cross-field validation)
        lat, lng = data.get('latitude'), data.get('longitude')
        instance = getattr(self, 'instance', None)
        if lat is not None or lng is not None:
            latitude = lat if lat is not None else (instance.latitude if instance else None)
            longitude = lng if lng is not None else (instance.longitude if instance else None)

            if not (loc := get_city_and_barangay(latitude, longitude)):
                errors["location"] = "Location must be within Metro Manila (NCR)."
            else:
                data.update({'city': loc['city'], 'barangay': loc['barangay']})

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        upload_file = validated_data.pop('upload', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        if upload_file:
            try:
                img = Image.open(upload_file)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)
                
                optimized_filename = f"{os.path.splitext(upload_file.name)[0]}.jpg"
                optimized_file = ContentFile(buffer.read(), name=optimized_filename)
                
                stored_path = default_storage.save(f"profile_photos/{optimized_filename}", optimized_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(optimized_filename)[:50]
                )
            except Exception as e:
                stored_path = default_storage.save(f"profile_photos/{upload_file.name}", upload_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(upload_file.name)[:50]
                )

        instance.save()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.upload:
            data['upload'] = build_upload_url(instance.upload, self.context)
        data.pop('password', None)
        return data


class TuabSelfSerializer(serializers.ModelSerializer):
    """Dedicated serializer for TUAB self-profile/session usage."""
    etag = serializers.SerializerMethodField(read_only=True)
    is_subscribed = serializers.SerializerMethodField(read_only=True)
    total_donations = serializers.SerializerMethodField(read_only=True)
    upload = serializers.SerializerMethodField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'role', 'business_name', 'description',
            'social_link', 'max_active_claims', 'target_fibers',
            'min_biodeg_score', 'max_distance_km', 'operational_status',
            'contact_no', 'barangay', 'city', 'latitude', 'longitude',
            'display_address', 'is_2fa_enabled', 'is_subscribed', 'total_donations', 'upload',
            'created_at', 'etag'
        ]

    def get_etag(self, obj):
        return build_updated_at_etag(obj)

    def get_is_subscribed(self, obj):
        annotated_value = getattr(obj, 'is_subscribed', None)
        if annotated_value is not None:
            return bool(annotated_value)
        return obj.subscriptions.filter(status=SubscriptionStatus.ACTIVE).exists()

    def get_total_donations(self, obj):
        return Donation.objects.filter(
            claimed_by_tuab_id=obj.user_id,
            status=DonationStatus.RECEIVED,
        ).count()

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


class AdminUserListSerializer(serializers.ModelSerializer):
    """Slim admin list serializer for user rows."""
    is_subscribed = serializers.SerializerMethodField(read_only=True)
    documentation = serializers.SerializerMethodField()
    upload = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'role', 'first_name', 'last_name', 'middle_name',
            'business_name', 'contact_no', 'status', 'is_subscribed', 'documentation', 'upload'
        ]

    def get_is_subscribed(self, obj):
        annotated_value = getattr(obj, 'is_subscribed', None)
        if annotated_value is not None:
            return bool(annotated_value)
        return obj.subscriptions.filter(status=SubscriptionStatus.ACTIVE).exists()

    def get_documentation(self, obj):
        return build_upload_url(obj.documentation, self.context)

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


class TuabListSerializer(serializers.ModelSerializer):
    """Slim serializer for non-admin TUAB list views."""
    upload = serializers.SerializerMethodField()
    distance_km = serializers.FloatField(read_only=True, required=False)

    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'role', 'business_name', 'description',
            'barangay', 'city', 'upload', 'distance_km', 'target_fibers'
        ]

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


class TuabDetailSerializer(serializers.ModelSerializer):
    """Limited profile serializer for non-admin TUAB detail views."""
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    upload = serializers.SerializerMethodField()
    total_donations = serializers.SerializerMethodField(read_only=True)
    distance_km = serializers.FloatField(read_only=True, required=False)

    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'role', 'business_name', 'description', 
            'social_link', 'contact_no', 'barangay', 'city', 'latitude', 
            'longitude', 'display_address', 'status', 'upload', 'distance_km',
            'target_fibers', 'min_biodeg_score', 'max_distance_km', 'operational_status',
            'total_donations',
        ]

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)

    def get_total_donations(self, obj):
        return Donation.objects.filter(
            claimed_by_tuab_id=obj.user_id,
            status=DonationStatus.RECEIVED,
        ).count()


class TwoFactorSerializer(serializers.Serializer):
    secret = serializers.CharField(min_length=32, max_length=32)
    otp_code = serializers.CharField(max_length=TEXT_FIELD_MAX_LENGTH)

    default_error_messages = {
        'invalid_otp': 'Invalid 2FA code.',
        'invalid_secret_length': '2FA secret must be exactly 32 characters.'
    }

    def validate_secret(self, value):
        if len(value) != 32:
            raise serializers.ValidationError(self.error_messages['invalid_secret_length'])
        return value

    def validate(self, data):
        totp = pyotp.TOTP(data['secret'])
        if not totp.verify(data['otp_code']):
            raise serializers.ValidationError({"detail": self.error_messages['invalid_otp']})
        return data


class MayaCardSerializer(serializers.Serializer):
    number = serializers.CharField(max_length=TEXT_FIELD_MAX_LENGTH)
    expMonth = serializers.CharField(max_length=TEXT_FIELD_MAX_LENGTH)
    expYear = serializers.CharField(max_length=TEXT_FIELD_MAX_LENGTH)
    cvc = serializers.CharField(max_length=TEXT_FIELD_MAX_LENGTH)


class SubscribeSetupSerializer(serializers.Serializer):
    firstName = serializers.CharField(max_length=TEXT_FIELD_MAX_LENGTH)
    lastName = serializers.CharField(max_length=TEXT_FIELD_MAX_LENGTH)
    card = MayaCardSerializer()


class DonorUpdateSelfSerializer(serializers.ModelSerializer):
    """Dedicated serializer for donor profile updates."""
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, max_length=User._meta.get_field('password').max_length)

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'middle_name', 'contact_no',
            'display_address', 'latitude', 'longitude', 'password', 'upload',
            'city', 'barangay'
        ]
        read_only_fields = ['city', 'barangay']
        extra_kwargs = {
            'display_address': {'max_length': TEXT_FIELD_MAX_LENGTH},
        }



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

    def validate_first_name(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_last_name(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_display_address(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_contact_no(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        if not re.match(r'^\+63\d{10}$', value):
            raise serializers.ValidationError("Phone must be +63 followed by 10 digits.")
        return value

    def validate_latitude(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return round(float(value), 7)

    def validate_longitude(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return round(float(value), 7)

    def validate(self, data):
        errors = {}

        # Location formatting and checking (Cross-field validation)
        lat, lng = data.get('latitude'), data.get('longitude')
        instance = getattr(self, 'instance', None)
        if lat is not None or lng is not None:
            latitude = lat if lat is not None else (instance.latitude if instance else None)
            longitude = lng if lng is not None else (instance.longitude if instance else None)

            if not (loc := get_city_and_barangay(latitude, longitude)):
                errors["location"] = "Location must be within Metro Manila (NCR)."
            else:
                data.update({'city': loc['city'], 'barangay': loc['barangay']})

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        upload_file = validated_data.pop('upload', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        if upload_file:
            try:
                img = Image.open(upload_file)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)
                
                optimized_filename = f"{os.path.splitext(upload_file.name)[0]}.jpg"
                optimized_file = ContentFile(buffer.read(), name=optimized_filename)
                
                stored_path = default_storage.save(f"profile_photos/{optimized_filename}", optimized_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(optimized_filename)[:50]
                )
            except Exception as e:
                stored_path = default_storage.save(f"profile_photos/{upload_file.name}", upload_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(upload_file.name)[:50]
                )

        instance.save()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.upload:
            data['upload'] = build_upload_url(instance.upload, self.context)
        data.pop('password', None)
        return data




class TuabUpdateSelfSerializer(serializers.ModelSerializer):
    """Dedicated serializer for TUAB profile updates."""
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, max_length=User._meta.get_field('password').max_length)

    class Meta:
        model = User
        fields = [
            'business_name', 'description', 'social_link', 'contact_no', 
            'max_distance_km', 'min_biodeg_score', 
            'operational_status', 'target_fibers', 'latitude', 'longitude', 
            'display_address', 'password', 'upload', 'city', 'barangay'
        ]
        read_only_fields = ['city', 'barangay']
        extra_kwargs = {
            'description': {'max_length': TEXT_FIELD_MAX_LENGTH},
            'social_link': {'max_length': TEXT_FIELD_MAX_LENGTH},
            'target_fibers': {'max_length': TEXT_FIELD_MAX_LENGTH},
            'display_address': {'max_length': TEXT_FIELD_MAX_LENGTH},
        }

    def validate_password(self, value):
        if len(value) < 8 or not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise serializers.ValidationError("Password must be at least 8 characters and contain both letters and numbers.")
        return value

    def validate_upload(self, v):
        if v:
            if v.size > 5242880: raise serializers.ValidationError("Image too large (max 5MB).")
            if not v.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                raise serializers.ValidationError("Invalid format (only JPG, JPEG, PNG allowed).")
        return v

    def validate_business_name(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_description(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_social_link(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_contact_no(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        if not re.match(r'^\+63\d{10}$', value):
            raise serializers.ValidationError("Phone must be +63 followed by 10 digits.")
        return value

    def validate_display_address(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_max_distance_km(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_min_biodeg_score(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_target_fibers(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError("This field may not be blank.")
        
        fibers = [f.strip().lower() for f in value.split(',') if f.strip()]
        db_fibers = get_allowed_fibers()
        invalid = [f for f in fibers if f not in db_fibers]
        if invalid:
            raise serializers.ValidationError(f"Invalid fibers (not in our database): {', '.join(invalid)}")
        return ','.join(fibers)

    def validate_latitude(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return round(float(value), 7)

    def validate_longitude(self, value):
        if value is None:
            raise serializers.ValidationError("This field may not be blank.")
        return round(float(value), 7)

    def validate(self, data):
        errors = {}

        # Location formatting and checking (Cross-field validation)
        lat, lng = data.get('latitude'), data.get('longitude')
        instance = getattr(self, 'instance', None)
        if lat is not None or lng is not None:
            latitude = lat if lat is not None else (instance.latitude if instance else None)
            longitude = lng if lng is not None else (instance.longitude if instance else None)

            if not (loc := get_city_and_barangay(latitude, longitude)):
                errors["location"] = "Location must be within Metro Manila (NCR)."
            else:
                data.update({'city': loc['city'], 'barangay': loc['barangay']})

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        upload_file = validated_data.pop('upload', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        if upload_file:
            try:
                img = Image.open(upload_file)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)
                
                optimized_filename = f"{os.path.splitext(upload_file.name)[0]}.jpg"
                optimized_file = ContentFile(buffer.read(), name=optimized_filename)
                
                stored_path = default_storage.save(f"profile_photos/{optimized_filename}", optimized_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(optimized_filename)[:50]
                )
            except Exception as e:
                stored_path = default_storage.save(f"profile_photos/{upload_file.name}", upload_file)
                instance.upload = Upload.objects.create(
                    file_path=stored_path,
                    name=os.path.basename(upload_file.name)[:50]
                )

        instance.save()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.upload:
            data['upload'] = build_upload_url(instance.upload, self.context)
        data.pop('password', None)
        return data


