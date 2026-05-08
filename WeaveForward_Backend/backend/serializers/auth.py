import io
import os
import re

import pyotp
from django.contrib.auth import authenticate
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image
from rest_framework import exceptions, serializers
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings

from ..constants import (
    ALLOWED_FIBERS,
    ALLOWED_IMAGE_EXTENSIONS,
    IMAGE_COMPRESSION_QUALITY,
    TUAB_REG_ALLOWED_EXTENSIONS,
    TUAB_REG_MAX_SIZE,
)
from ..models import Upload, User, UserAccountStatus
from ..services.auth_service import reset_user_password, validate_reset_token
from ..services.location_service import get_city_and_barangay


class DonorRegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(validators=[UniqueValidator(queryset=User.objects.all())])
    password = serializers.CharField(write_only=True)
    middle_name = serializers.CharField(required=False, allow_blank=True)
    display_address = serializers.CharField()
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7)

    class Meta:
        model = User
        fields = [
            'first_name', 'middle_name', 'last_name', 'email',
            'contact_no', 'password',
            'display_address', 'latitude', 'longitude'
        ]

    def validate(self, data):
        # 1. Password strength
        pw = data.get('password', '')
        if len(pw) < 8 or not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
            raise serializers.ValidationError({"password": "Password must be at least 8 characters and contain both letters and numbers."})

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
        validated_data['role'], validated_data['status'] = role, 'ACTIVE'
        return User.objects.create_user(password=password, **validated_data)


class TUABRegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(validators=[UniqueValidator(queryset=User.objects.all())])
    password = serializers.CharField(write_only=True)
    business_name = serializers.CharField()
    display_address = serializers.CharField()
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7)
    description = serializers.CharField(required=False)
    social_link = serializers.URLField(required=False)
    target_fibers = serializers.CharField(required=True)
    max_distance_km = serializers.DecimalField(max_digits=5, decimal_places=2)
    min_biodeg_score = serializers.DecimalField(max_digits=5, decimal_places=2)
    documentation = serializers.FileField(required=True)

    class Meta:
        model = User
        fields = [
            'business_name', 'email', 'contact_no', 'password',
            'description', 'social_link', 'display_address', 'latitude', 'longitude',
            'target_fibers', 'max_distance_km', 'min_biodeg_score', 'documentation'
        ]

    def validate(self, data):
        # 1. Password strength
        pw = data.get('password', '')
        if len(pw) < 8 or not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
            raise serializers.ValidationError({"password": "Password must be at least 8 characters and contain both letters and numbers."})

        # 2. Phone validation
        if not re.match(r'^\+63\d{10}$', data.get('contact_no', '')):
            raise serializers.ValidationError({"contact_no": "Phone must be +63 followed by 10 digits."})

        # 3. File validation (TUAB Specific Extensions & Size)
        documentation = self.initial_data.get('documentation')
        if documentation:
            ext = os.path.splitext(documentation.name)[1].lower()
            if ext not in TUAB_REG_ALLOWED_EXTENSIONS:
                raise serializers.ValidationError({"documentation": f"Only {', '.join(TUAB_REG_ALLOWED_EXTENSIONS)} files are allowed for registration."})
            if hasattr(documentation, 'size') and documentation.size > TUAB_REG_MAX_SIZE:
                raise serializers.ValidationError({"documentation": f"File size must be under {TUAB_REG_MAX_SIZE // (1024*1024)}MB."})

        # 4. Strict Fiber Format and Whitelist Validation
        raw_fibers = data.get('target_fibers', '')
        if ' ' in raw_fibers or any(c.isupper() for c in raw_fibers):
            raise serializers.ValidationError({"target_fibers": "Fibers must be strictly lowercase and comma-separated with no spaces."})

        input_fibers = [f for f in raw_fibers.split(',') if f]
        if not input_fibers:
            raise serializers.ValidationError({"target_fibers": "At least one preferred fiber type is required."})

        invalid = [f for f in input_fibers if f not in ALLOWED_FIBERS]
        if invalid:
            raise serializers.ValidationError({"target_fibers": f"Invalid fibers: {', '.join(invalid)}"})
        data['target_fibers'] = raw_fibers

        # 5. Coordinate precision check
        raw_lat = str(self.initial_data.get('latitude', ''))
        raw_lng = str(self.initial_data.get('longitude', ''))
        if '.' not in raw_lat or len(raw_lat.split('.')[-1]) != 7 or '.' not in raw_lng or len(raw_lng.split('.')[-1]) != 7:
            raise serializers.ValidationError({"location": "Coordinates must be sent with exactly 7 decimal places."})

        # 6. NCR Lookup
        loc = get_city_and_barangay(data.get('latitude'), data.get('longitude'))
        if not loc:
            raise serializers.ValidationError({"location": "Location must be within Metro Manila (NCR)."})
        data['city'], data['barangay'] = loc['city'], loc['barangay']

        return data

    def create(self, validated_data):
        documentation = validated_data.pop('documentation', None)
        role, password = validated_data.pop('role', 'TUAB'), validated_data.pop('password')
        validated_data['role'], validated_data['status'] = role, 'UNDER_REVIEW'

        # Process and Minify image files
        if documentation:
            ext = os.path.splitext(documentation.name)[1].lower()
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                img = Image.open(documentation)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=IMAGE_COMPRESSION_QUALITY, optimize=True)
                documentation = ContentFile(buffer.getvalue(), name=os.path.splitext(documentation.name)[0] + ".jpg")

            path = default_storage.save(f'documentation/{documentation.name}', documentation)
            validated_data['documentation'] = Upload.objects.create(file_path=path, name=documentation.name)

        return User.objects.create_user(password=password, **validated_data)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    otp_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    default_error_messages = {
        'no_active_account': 'Invalid email or password.',
        'invalid_otp': 'Invalid 2FA code.'
    }

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims
        token['role'] = user.role
        token['email'] = user.email
        token['name'] = user.business_name if user.role == 'TUAB' else f"{user.first_name} {user.last_name}"
        return token

    def validate(self, attrs):
        authenticate_kwargs = {
            self.username_field: attrs[self.username_field],
            'password': attrs['password'],
        }
        request = self.context.get('request')
        if request is not None:
            authenticate_kwargs['request'] = request

        self.user = authenticate(**authenticate_kwargs)
        if not api_settings.USER_AUTHENTICATION_RULE(self.user):
            raise exceptions.AuthenticationFailed(
                self.error_messages['no_active_account'],
                'no_active_account'
            )

        # Check if the account is ACTIVE
        if self.user.status != UserAccountStatus.ACTIVE:
            if self.user.status == UserAccountStatus.UNDER_REVIEW:
                error_msg = "Your account is still under review."
            elif self.user.status == UserAccountStatus.REJECTED:
                error_msg = "Your registration was rejected."
            else:
                # Use the generic message for ARCHIVED or other statuses
                error_msg = self.error_messages['no_active_account']
            raise exceptions.AuthenticationFailed({"detail": error_msg})

        # --- 2FA CHECK ---
        if self.user.is_2fa_enabled:
            otp_code = attrs.get('otp_code')
            if not otp_code:
                # Signal to frontend that 2FA is needed
                raise serializers.ValidationError({
                    "2fa_required": True,
                    "detail": "2FA code required."
                })

            # Verify the OTP code
            totp = pyotp.TOTP(self.user.totp_secret)
            if not totp.verify(otp_code):
                raise serializers.ValidationError({"detail": self.error_messages['invalid_otp']})

        refresh = self.get_token(self.user)
        data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

        # Add extra info to the JSON response
        data['user_id'] = self.user.user_id
        data['role'] = self.user.role
        data['email'] = self.user.email
        data['name'] = self.user.business_name if self.user.role == 'TUAB' else f"{self.user.first_name} {self.user.last_name}"
        return data


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uidb64 = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)

    def validate(self, data):

        if len(data['new_password']) < 8 or not any(c.isalpha() for c in data['new_password']) or not any(c.isdigit() for c in data['new_password']):
            raise serializers.ValidationError({"password": "Password must be at least 8 characters and contain both letters and numbers."})

        user = validate_reset_token(data['uidb64'], data['token'])
        if not user:
            raise serializers.ValidationError({"token": "Invalid or expired token."})

        if not user.is_active:
            raise serializers.ValidationError({"token": "This account is no longer eligible for password reset."})

        self.user = user
        return data

    def save(self):
        reset_user_password(self.user, self.validated_data['new_password'])
        return self.user

