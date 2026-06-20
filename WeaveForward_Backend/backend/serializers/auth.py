import os
import re

import pyotp
from django.contrib.auth import authenticate
from rest_framework import exceptions, serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings

from ..constants import TUAB_REG_ALLOWED_EXTENSIONS, TUAB_REG_MAX_SIZE
from ..models import User, UserAccountStatus
from ..services.auth_service import reset_user_password, validate_reset_token
from ..services.location_service import get_city_and_barangay
from ..services.brand_fiber_lookup_service import get_allowed_fibers


class DonorRegisterSerializer(serializers.ModelSerializer):
    middle_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = User
        fields = [
            'first_name', 'middle_name', 'last_name', 'email',
            'contact_no', 'password',
            'display_address', 'latitude', 'longitude'
        ]

    def validate(self, data):
        # Email
        email = data.get('email', '')
        if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
            raise serializers.ValidationError({'email': "Please enter a valid email address."})
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError({'email': "Email already taken."})

        # Phone
        contact_no = data.get('contact_no', '')
        if not re.match(r'^\+63\d{10}$', contact_no):
            raise serializers.ValidationError({'contact_no': "Enter a valid Philippine mobile number starting with +63 (e.g., +639171234567)."})
        if User.objects.filter(contact_no=contact_no).exists():
            raise serializers.ValidationError({'contact_no': "Phone already taken."})

        # Password
        pw = data.get('password', '') or ''
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{}|;:\'",.<>?/`~\\]).{8,}$', pw):
            raise serializers.ValidationError({'password': "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, a number, and a special character."})

        # Location
        lat, lng = data.get('latitude'), data.get('longitude')
        loc = get_city_and_barangay(lat, lng)
        if not loc:
            raise serializers.ValidationError({'latitude': "Location must be within Metro Manila."})
        data['city'], data['barangay'] = loc['city'], loc['barangay']

        return data

    def create(self, validated_data):
        role, password = validated_data.pop('role', 'Donor'), validated_data.pop('password')
        validated_data['role'] = role
        validated_data['status'] = UserAccountStatus.EMAIL_UNVERIFIED
        return User.objects.create_user(password=password, **validated_data)


class TUABRegisterSerializer(serializers.ModelSerializer):
    documentation = serializers.FileField()

    class Meta:
        model = User
        fields = [
            'business_name', 'email', 'contact_no', 'password',
            'description', 'social_link', 'display_address', 'latitude', 'longitude',
            'target_fibers', 'max_distance_km', 'min_biodeg_score', 'documentation'
        ]

    def validate(self, data):
        # Email
        email = data.get('email', '')
        if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
            raise serializers.ValidationError({'email': "Please enter a valid email address."})
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError({'email': "Email already taken."})

        # Phone
        contact_no = data.get('contact_no', '')
        if not re.match(r'^\+63\d{10}$', contact_no):
            raise serializers.ValidationError({'contact_no': "Enter a valid Philippine mobile number starting with +63 (e.g., +639171234567)."})
        if User.objects.filter(contact_no=contact_no).exists():
            raise serializers.ValidationError({'contact_no': "Phone already taken."})

        # Password
        pw = data.get('password', '') or ''
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{}|;:\'",.<>?/`~\\]).{8,}$', pw):
            raise serializers.ValidationError({'password': "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, a number, and a special character."})

        # File
        documentation = self.initial_data.get('documentation')
        if os.path.splitext(documentation.name)[1].lower() not in TUAB_REG_ALLOWED_EXTENSIONS or documentation.size > TUAB_REG_MAX_SIZE:
            raise serializers.ValidationError({'documentation': "Please upload a PDF, JPG, or PNG file under 50 MB."})

        # Fibers
        input_fibers = [f for f in (data.get('target_fibers') or '').split(',') if f]
        for f in input_fibers:
            if f not in get_allowed_fibers():
                raise serializers.ValidationError({'target_fibers': f"{f} is not a recognized fiber type."})
        data['target_fibers'] = ','.join(input_fibers)

        # Location
        lat, lng = data.get('latitude'), data.get('longitude')
        loc = get_city_and_barangay(lat, lng)
        if not loc:
            raise serializers.ValidationError({'latitude': "Location must be within Metro Manila."})
        data['city'], data['barangay'] = loc['city'], loc['barangay']

        # Max Distance
        if data['max_distance_km'] < 0 or data['max_distance_km'] > 1000:
            raise serializers.ValidationError({'max_distance_km': "Must be between 0 and 1000 km."})

        # Min Biodeg Score
        if data['min_biodeg_score'] < 0 or data['min_biodeg_score'] > 100:
            raise serializers.ValidationError({'min_biodeg_score': "Must be between 0 and 100."})

        return data

    def create(self, validated_data):
        role, password = validated_data.pop('role', 'TUAB'), validated_data.pop('password')
        validated_data['role'] = role
        validated_data['status'] = UserAccountStatus.EMAIL_UNVERIFIED
        return User.objects.create_user(password=password, **validated_data)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    otp_code = serializers.CharField(required=False)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['status'] = user.status
        return token

    default_error_messages = {
        'no_active_account': 'Invalid email or password.',
        'invalid_otp': 'Invalid 2FA code.'
    }

    def validate(self, attrs):
        email = attrs.get(self.username_field)
        password = attrs.get('password')

        # PRE-CHECK: Show REJECTED / EMAIL_UNVERIFIED users their specific reason (authenticate() would hide it)
        try:
            user_check = User.objects.get(email=email)
            if user_check.status == UserAccountStatus.REJECTED and user_check.check_password(password):
                raise exceptions.AuthenticationFailed({"detail": f"Your registration was rejected. {user_check.rejection_reason}"})
            if user_check.status == UserAccountStatus.EMAIL_UNVERIFIED and user_check.check_password(password):
                raise exceptions.AuthenticationFailed({"detail": "Please verify your email before logging in."})
        except User.DoesNotExist:
            pass

        # Authenticate
        request = self.context.get('request')
        self.user = authenticate(**{self.username_field: email, 'password': password, **({"request": request} if request else {})})
        if not api_settings.USER_AUTHENTICATION_RULE(self.user):
            raise exceptions.AuthenticationFailed(self.error_messages['no_active_account'], 'no_active_account')

        # Status check
        if self.user.status != UserAccountStatus.ACTIVE:
            msg = "Your account is still under review." if self.user.status == UserAccountStatus.UNDER_REVIEW else self.error_messages['no_active_account']
            raise exceptions.AuthenticationFailed({"detail": msg})

        # 2FA
        if self.user.is_2fa_enabled:
            otp_code = attrs.get('otp_code')
            if not otp_code:
                raise serializers.ValidationError({"2fa_required": True, "detail": "2FA code required."})
            if not pyotp.TOTP(self.user.totp_secret).verify(otp_code):
                raise serializers.ValidationError({"detail": self.error_messages['invalid_otp']})

        # Token
        refresh = self.get_token(self.user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user_id': self.user.user_id,
            'role': self.user.role,
        }


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=User._meta.get_field('email').max_length)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uidb64 = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, max_length=User._meta.get_field('password').max_length)

    def validate(self, data):

        pw = data.get('new_password', '') or ''
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{}|;:\'",.<>?/`~\\]).{8,}$', pw):
            raise serializers.ValidationError({'password': "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, a number, and a special character."})

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
