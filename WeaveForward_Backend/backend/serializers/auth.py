import io
import os
import re
from decimal import Decimal

import pyotp
import uuid
from django.contrib.auth import authenticate
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image
from rest_framework import exceptions, serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings

from ..constants import (
    ALLOWED_IMAGE_EXTENSIONS,
    IMAGE_COMPRESSION_QUALITY,
    TUAB_REG_ALLOWED_EXTENSIONS,
    TUAB_REG_MAX_SIZE,
)
from ..models import Upload, User, UserAccountStatus, UserOperationalStatus
from ..services.auth_service import reset_user_password, validate_reset_token
from ..services.location_service import get_city_and_barangay
from ..services.brand_fiber_lookup_service import get_allowed_fibers


class DonorRegisterSerializer(serializers.ModelSerializer):
    email = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    contact_no = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = User
        fields = [
            'first_name', 'middle_name', 'last_name', 'email',
            'contact_no', 'password',
            'display_address', 'latitude', 'longitude'
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False, 'allow_null': True, 'allow_blank': True},
            'first_name': {'required': False, 'allow_null': True, 'allow_blank': True},
            'last_name': {'required': False, 'allow_null': True, 'allow_blank': True},
            'middle_name': {'required': False, 'allow_null': True, 'allow_blank': True},
            'display_address': {'required': False, 'allow_null': True, 'allow_blank': True},
            'latitude': {'required': False, 'allow_null': True},
            'longitude': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        errors = {}

        # 1. First Name
        first_name = (data.get('first_name') or '').strip()
        if not first_name:
            errors["first_name"] = ["First name is required."]
        elif len(first_name) > 50:
            errors["first_name"] = ["Ensure this field has no more than 50 characters."]

        # 2. Last Name
        last_name = (data.get('last_name') or '').strip()
        if not last_name:
            errors["last_name"] = ["Last name is required."]
        elif len(last_name) > 50:
            errors["last_name"] = ["Ensure this field has no more than 50 characters."]

        # 3. Middle Name
        middle_name = (data.get('middle_name') or '').strip()
        if middle_name and len(middle_name) > 50:
            errors["middle_name"] = ["Ensure this field has no more than 50 characters."]

        # 4. Email validation
        email = (data.get('email') or '').strip()
        if not email:
            errors["email"] = ["Email is required."]
        elif len(email) > 100:
            errors["email"] = ["Ensure this field has no more than 100 characters."]
        elif not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
            errors["email"] = ["Enter a valid email address."]
        elif User.objects.filter(email__iexact=email).exists():
            errors["email"] = ["User with this email already exists."]

        # 5. Phone validation
        contact_no = (data.get('contact_no') or '').strip()
        if not contact_no:
            errors["contact_no"] = ["Phone must be +63 followed by 10 digits."]
        elif not re.match(r'^\+63\d{10}$', contact_no):
            errors["contact_no"] = ["Phone must be +63 followed by 10 digits."]
        elif User.objects.filter(contact_no=contact_no).exists():
            errors["contact_no"] = ["User with this phone number already exists."]

        # 6. Password strength
        pw = data.get('password', '') or ''
        if not pw:
            errors["password"] = ["Password is required."]
        elif len(pw) < 8 or not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
            errors["password"] = ["Password must be at least 8 characters and contain both letters and numbers."]

        # 7. Display address
        display_address = (data.get('display_address') or '').strip()
        if not display_address:
            errors["display_address"] = ["Display address is required."]

        # 8. Coordinates & NCR lookup
        raw_lat = str(self.initial_data.get('latitude') or '').strip()
        raw_lng = str(self.initial_data.get('longitude') or '').strip()
        coord_error = False
        if not raw_lat or not raw_lng:
            errors["location"] = ["Coordinates are required."]
            coord_error = True
        elif '.' not in raw_lat or len(raw_lat.split('.')[-1]) != 7 or '.' not in raw_lng or len(raw_lng.split('.')[-1]) != 7:
            errors["location"] = ["Coordinates must be sent with exactly 7 decimal places."]
            coord_error = True

        if not coord_error:
            try:
                lat = Decimal(raw_lat)
                lng = Decimal(raw_lng)
                loc = get_city_and_barangay(lat, lng)
                if not loc:
                    errors["location"] = ["Location must be within Metro Manila (NCR)."]
                else:
                    data['latitude'] = lat
                    data['longitude'] = lng
                    data['city'], data['barangay'] = loc['city'], loc['barangay']
            except (ValueError, TypeError, ArithmeticError):
                errors["location"] = ["Invalid coordinate format."]

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def create(self, validated_data):
        # Setup role and active status for Donors
        role, password = validated_data.pop('role', 'Donor'), validated_data.pop('password')
        validated_data['role'], validated_data['status'] = role, 'ACTIVE'
        return User.objects.create_user(password=password, **validated_data)


class TUABRegisterSerializer(serializers.ModelSerializer):
    social_link = serializers.URLField(required=False)
    documentation = serializers.FileField(required=False, allow_null=True)
    email = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    contact_no = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = User
        fields = [
            'business_name', 'email', 'contact_no', 'password',
            'description', 'social_link', 'display_address', 'latitude', 'longitude',
            'target_fibers', 'max_distance_km', 'min_biodeg_score', 'documentation'
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False, 'allow_null': True, 'allow_blank': True},
            'business_name': {'required': False, 'allow_null': True, 'allow_blank': True},
            'description': {'required': False, 'allow_null': True, 'allow_blank': True},
            'display_address': {'required': False, 'allow_null': True, 'allow_blank': True},
            'latitude': {'required': False, 'allow_null': True},
            'longitude': {'required': False, 'allow_null': True},
            'target_fibers': {'required': False, 'allow_null': True, 'allow_blank': True},
            'max_distance_km': {'required': False, 'allow_null': True},
            'min_biodeg_score': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        errors = {}

        # 1. Business Name
        business_name = (data.get('business_name') or '').strip()
        if not business_name:
            errors["business_name"] = ["Business name is required."]
        elif len(business_name) > 125:
            errors["business_name"] = ["Ensure this field has no more than 125 characters."]

        # 2. Email validation
        email = (data.get('email') or '').strip()
        if not email:
            errors["email"] = ["Email is required."]
        elif len(email) > 100:
            errors["email"] = ["Ensure this field has no more than 100 characters."]
        elif not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
            errors["email"] = ["Enter a valid email address."]
        elif User.objects.filter(email__iexact=email).exists():
            errors["email"] = ["User with this email already exists."]

        # 3. Phone validation
        contact_no = (data.get('contact_no') or '').strip()
        if not contact_no:
            errors["contact_no"] = ["Phone must be +63 followed by 10 digits."]
        elif not re.match(r'^\+63\d{10}$', contact_no):
            errors["contact_no"] = ["Phone must be +63 followed by 10 digits."]
        elif User.objects.filter(contact_no=contact_no).exists():
            errors["contact_no"] = ["User with this phone number already exists."]

        # 4. Password strength
        pw = data.get('password', '') or ''
        if not pw:
            errors["password"] = ["Password is required."]
        elif len(pw) < 8 or not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
            errors["password"] = ["Password must be at least 8 characters and contain both letters and numbers."]

        # 5. Description validation
        description = (data.get('description') or '').strip()
        if not description:
            errors["description"] = ["Description is required."]

        # 6. Display address
        display_address = (data.get('display_address') or '').strip()
        if not display_address:
            errors["display_address"] = ["Display address is required."]

        # 7. File validation (TUAB Specific Extensions & Size)
        documentation = self.initial_data.get('documentation') or data.get('documentation')
        if not documentation:
            errors["documentation"] = ["No file was submitted."]
        else:
            ext = os.path.splitext(documentation.name)[1].lower()
            if ext not in TUAB_REG_ALLOWED_EXTENSIONS:
                errors["documentation"] = [f"Only {', '.join(TUAB_REG_ALLOWED_EXTENSIONS)} files are allowed for registration."]
            if hasattr(documentation, 'size') and documentation.size > TUAB_REG_MAX_SIZE:
                errors["documentation"] = [f"File size must be under {TUAB_REG_MAX_SIZE // (1024*1024)}MB."]

        # 8. Strict Fiber Format and Whitelist Validation
        raw_fibers = (data.get('target_fibers') or '').strip()
        if not raw_fibers:
            errors["target_fibers"] = ["At least one preferred fiber type is required."]
        elif ' ' in raw_fibers or any(c.isupper() for c in raw_fibers):
            errors["target_fibers"] = ["Fibers must be strictly lowercase and comma-separated with no spaces."]
        else:
            input_fibers = [f for f in raw_fibers.split(',') if f]
            if not input_fibers:
                errors["target_fibers"] = ["At least one preferred fiber type is required."]
            else:
                db_fibers = get_allowed_fibers()
                invalid = [f for f in input_fibers if f not in db_fibers]
                if invalid:
                    errors["target_fibers"] = [f"Invalid fibers (not in our database): {', '.join(invalid)}"]
                else:
                    data['target_fibers'] = raw_fibers

        # 9. Coordinates & NCR lookup
        raw_lat = str(self.initial_data.get('latitude') or '').strip()
        raw_lng = str(self.initial_data.get('longitude') or '').strip()
        coord_error = False
        if not raw_lat or not raw_lng:
            errors["location"] = ["Coordinates are required."]
            coord_error = True
        elif '.' not in raw_lat or len(raw_lat.split('.')[-1]) != 7 or '.' not in raw_lng or len(raw_lng.split('.')[-1]) != 7:
            errors["location"] = ["Coordinates must be sent with exactly 7 decimal places."]
            coord_error = True

        if not coord_error:
            try:
                lat = Decimal(raw_lat)
                lng = Decimal(raw_lng)
                loc = get_city_and_barangay(lat, lng)
                if not loc:
                    errors["location"] = ["Location must be within Metro Manila (NCR)."]
                else:
                    data['latitude'] = lat
                    data['longitude'] = lng
                    data['city'], data['barangay'] = loc['city'], loc['barangay']
            except (ValueError, TypeError, ArithmeticError):
                errors["location"] = ["Invalid coordinate format."]

        # 10. Max Distance
        raw_dist = data.get('max_distance_km')
        if raw_dist is None or (isinstance(raw_dist, str) and not raw_dist.strip()):
            errors["max_distance_km"] = ["Max distance is required."]
        else:
            try:
                dist = Decimal(str(raw_dist))
                if dist < 0 or dist > 1000:
                    errors["max_distance_km"] = ["Max distance must be between 0 and 1000 km."]
                else:
                    data['max_distance_km'] = dist
            except (ValueError, TypeError, ArithmeticError):
                errors["max_distance_km"] = ["A valid number is required."]

        # 11. Min Biodeg Score
        raw_score = data.get('min_biodeg_score')
        if raw_score is None or (isinstance(raw_score, str) and not raw_score.strip()):
            errors["min_biodeg_score"] = ["Min. Biodegradability Score is required."]
        else:
            try:
                score = Decimal(str(raw_score))
                if score < 0 or score > 100:
                    errors["min_biodeg_score"] = ["Min. Biodegradability Score must be between 0 and 100."]
                else:
                    data['min_biodeg_score'] = score
            except (ValueError, TypeError, ArithmeticError):
                errors["min_biodeg_score"] = ["A valid number is required."]

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def create(self, validated_data):
        documentation = validated_data.pop('documentation', None)
        role, password = validated_data.pop('role', 'TUAB'), validated_data.pop('password')
        validated_data['role'], validated_data['status'] = role, 'UNDER_REVIEW'
        validated_data['operational_status'] = UserOperationalStatus.ACTIVE

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

            safe_name = f"{uuid.uuid4().hex}{os.path.splitext(documentation.name)[1]}"
            path = default_storage.save(f'documentation/{safe_name}', documentation)
            validated_data['documentation'] = Upload.objects.create(file_path=path, name=os.path.basename(safe_name))

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
        return token

    def validate(self, attrs):
        email = attrs.get(self.username_field)
        password = attrs.get('password')
        
        # PRE-CHECK: Django's `authenticate` silently rejects users if `is_active=False`.
        # We manually intercept REJECTED users here so we can show their specific reason,
        # but ONLY if they provide the correct password to prevent status-leaking.
        if email and password:
            try:
                user_check = User.objects.get(email=email)
                if user_check.status == UserAccountStatus.REJECTED and user_check.check_password(password):
                    reason = getattr(user_check, 'rejection_reason', None)
                    if reason:
                        error_msg = f"Your registration was rejected. Reason: {reason}"
                    else:
                        error_msg = "Your registration was rejected."
                    raise exceptions.AuthenticationFailed({"detail": error_msg})
            except User.DoesNotExist:
                pass

        authenticate_kwargs = {
            self.username_field: email,
            'password': password,
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

        # Check if the account is ACTIVE (Under Review and Archived handling)
        if self.user.status != UserAccountStatus.ACTIVE:
            if self.user.status == UserAccountStatus.UNDER_REVIEW:
                error_msg = "Your account is still under review."
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
