import os
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
import pyotp
import uuid
import re
from rest_framework import serializers

from ..models import Donation, DonationStatus, SubscriptionStatus, Upload, User, UserRole
from ..services.upload_service import build_upload_url
from ..services.location_service import get_city_and_barangay
from ..services.brand_fiber_lookup_service import get_allowed_fibers


class AdminUserDetailSerializer(serializers.ModelSerializer):
    """Full user profile serializer used exclusively by Admins for viewing details."""
    is_subscribed = serializers.SerializerMethodField(read_only=True)
    total_donations = serializers.SerializerMethodField(read_only=True)
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
            'created_at', 'updated_at', 'distance_km'
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
    upload = serializers.SerializerMethodField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'role', 'first_name', 'last_name', 'middle_name',
            'contact_no', 'barangay', 'city', 'latitude', 'longitude',
            'display_address', 'is_2fa_enabled', 'upload', 'created_at',
            'updated_at'
        ]

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


class DonorUpdateSerializer(serializers.ModelSerializer):
    """Dedicated serializer for donor profile updates."""
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'middle_name', 'contact_no',
            'display_address', 'latitude', 'longitude', 'password', 'upload',
            'city', 'barangay'
        ]
        read_only_fields = ['city', 'barangay']

    def validate(self, data):
        # 1. Password
        pw = data.get('password')
        if pw and not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{}|;:\'",.<>?/`~\\]).{8,}$', pw):
            raise serializers.ValidationError({'password': "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, a number, and a special character."})

        # 2. Upload
        if data.get('upload') and (data['upload'].size > 5242880 or not data['upload'].name.lower().endswith(('.jpg', '.jpeg', '.png'))):
            raise serializers.ValidationError({'upload': "Please upload a JPG or PNG image under 5 MB."})

        # 3. Contact No
        contact_no = data.get('contact_no')
        if contact_no and not re.match(r'^\+63\d{10}$', contact_no):
            raise serializers.ValidationError({'contact_no': "Enter a valid Philippine mobile number starting with +63 (e.g., +639171234567)."})

        # 4. Location
        lat, lng = data.get('latitude'), data.get('longitude')
        if lat is not None and lng is not None:
            loc = get_city_and_barangay(lat, lng)
            if not loc:
                raise serializers.ValidationError({'location': "Location must be within Metro Manila."})
            data.update({'city': loc['city'], 'barangay': loc['barangay']})

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
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'business_name', 'description', 'social_link', 'contact_no', 
            'max_active_claims', 'max_distance_km', 'min_biodeg_score', 
            'operational_status', 'target_fibers', 'latitude', 'longitude', 
            'display_address', 'password', 'upload', 'city', 'barangay'
        ]
        read_only_fields = ['city', 'barangay']

    def validate(self, data):
        # 1. Password
        pw = data.get('password')
        if pw and not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{}|;:\'",.<>?/`~\\]).{8,}$', pw):
            raise serializers.ValidationError({'password': "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, a number, and a special character."})

        # 2. Upload
        if data.get('upload') and (data['upload'].size > 5242880 or not data['upload'].name.lower().endswith(('.jpg', '.jpeg', '.png'))):
            raise serializers.ValidationError({'upload': "Please upload a JPG or PNG image under 5 MB."})

        # 3. Contact No
        contact_no = data.get('contact_no')
        if contact_no and not re.match(r'^\+63\d{10}$', contact_no):
            raise serializers.ValidationError({'contact_no': "Enter a valid Philippine mobile number starting with +63 (e.g., +639171234567)."})

        # 4. Target Fibers
        if 'target_fibers' in data:
            fibers = data.get('target_fibers')
            input_fibers = [f for f in (fibers or '').split(',') if f]
            if not input_fibers:
                raise serializers.ValidationError({'target_fibers': "Select at least one fiber type you accept."})
            for f in input_fibers:
                if f not in get_allowed_fibers():
                    raise serializers.ValidationError({'target_fibers': f"{f} is not a recognized fiber type."})
            data['target_fibers'] = ','.join(input_fibers)

        # 5. Location
        lat, lng = data.get('latitude'), data.get('longitude')
        if lat is not None and lng is not None:
            loc = get_city_and_barangay(lat, lng)
            if not loc:
                raise serializers.ValidationError({'location': "Location must be within Metro Manila."})
            data.update({'city': loc['city'], 'barangay': loc['barangay']})

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


class TuabSelfSerializer(serializers.ModelSerializer):
    """Dedicated serializer for TUAB self-profile/session usage."""
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
            'created_at'
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
            'business_name', 'contact_no', 'display_address', 'barangay', 'city',
            'latitude', 'longitude',
            'target_fibers', 'max_distance_km', 'min_biodeg_score',
            'social_link', 'description', 'operational_status',
            'status', 'is_subscribed', 'documentation', 'upload'
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
    otp_code = serializers.CharField()

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
    number = serializers.CharField()
    expMonth = serializers.CharField()
    expYear = serializers.CharField()
    cvc = serializers.CharField()


class SubscribeSetupSerializer(serializers.Serializer):
    firstName = serializers.CharField()
    lastName = serializers.CharField()
    card = MayaCardSerializer()


class DonorUpdateSelfSerializer(serializers.ModelSerializer):
    """Dedicated serializer for donor profile updates."""
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'middle_name', 'contact_no',
            'display_address', 'latitude', 'longitude', 'password', 'upload',
            'city', 'barangay'
        ]
        read_only_fields = ['city', 'barangay']

    def validate(self, data):
        # 1. Password
        pw = data.get('password')
        if pw and not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{}|;:\'",.<>?/`~\\]).{8,}$', pw):
            raise serializers.ValidationError({'password': "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, a number, and a special character."})

        # 2. Upload
        if data.get('upload') and (data['upload'].size > 5242880 or not data['upload'].name.lower().endswith(('.jpg', '.jpeg', '.png'))):
            raise serializers.ValidationError({'upload': "Please upload a JPG or PNG image under 5 MB."})

        # 3. Contact No
        contact_no = data.get('contact_no')
        if contact_no and not re.match(r'^\+63\d{10}$', contact_no):
            raise serializers.ValidationError({'contact_no': "Enter a valid Philippine mobile number starting with +63 (e.g., +639171234567)."})

        # 4. Location
        lat, lng = data.get('latitude'), data.get('longitude')
        if lat is not None and lng is not None:
            loc = get_city_and_barangay(lat, lng)
            if not loc:
                raise serializers.ValidationError({'location': "Location must be within Metro Manila."})
            data.update({'city': loc['city'], 'barangay': loc['barangay']})

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




class TuabUpdateSelfSerializer(serializers.ModelSerializer):
    """Dedicated serializer for TUAB profile updates."""
    upload = serializers.FileField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'business_name', 'description', 'social_link', 'contact_no', 
            'max_distance_km', 'min_biodeg_score', 
            'operational_status', 'target_fibers', 'latitude', 'longitude', 
            'display_address', 'password', 'upload', 'city', 'barangay'
        ]
        read_only_fields = ['city', 'barangay']

    def validate(self, data):
        # 1. Password
        pw = data.get('password')
        if pw and not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{}|;:\'",.<>?/`~\\]).{8,}$', pw):
            raise serializers.ValidationError({'password': "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, a number, and a special character."})

        # 2. Upload
        if data.get('upload') and (data['upload'].size > 5242880 or not data['upload'].name.lower().endswith(('.jpg', '.jpeg', '.png'))):
            raise serializers.ValidationError({'upload': "Please upload a JPG or PNG image under 5 MB."})

        # 3. Contact No
        contact_no = data.get('contact_no')
        if contact_no and not re.match(r'^\+63\d{10}$', contact_no):
            raise serializers.ValidationError({'contact_no': "Enter a valid Philippine mobile number starting with +63 (e.g., +639171234567)."})

        # 4. Target Fibers
        if 'target_fibers' in data:
            fibers = data.get('target_fibers')
            input_fibers = [f for f in (fibers or '').split(',') if f]
            if not input_fibers:
                raise serializers.ValidationError({'target_fibers': "Select at least one fiber type you accept."})
            for f in input_fibers:
                if f not in get_allowed_fibers():
                    raise serializers.ValidationError({'target_fibers': f"{f} is not a recognized fiber type."})
            data['target_fibers'] = ','.join(input_fibers)

        # 5. Location
        lat, lng = data.get('latitude'), data.get('longitude')
        if lat is not None and lng is not None:
            loc = get_city_and_barangay(lat, lng)
            if not loc:
                raise serializers.ValidationError({'location': "Location must be within Metro Manila."})
            data.update({'city': loc['city'], 'barangay': loc['barangay']})

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


