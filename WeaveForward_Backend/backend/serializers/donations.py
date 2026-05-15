import re
import json
import os
from datetime import timedelta
from django.utils import timezone
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from rest_framework import serializers

from ..models import (
    BrandFiberLookup, Donation, DonationItem, Upload, User, 
    UserAccountStatus, UserRole, DonationStatus, DonationItemConditionRating, Order
)
from ..services.location_service import get_city_and_barangay
from ..services.upload_service import build_upload_url


from .brandfiberlookups import BrandFiberLookupSerializer


class DonationItemSerializer(serializers.ModelSerializer):
    lookup_details = BrandFiberLookupSerializer(source='lookup', read_only=True)

    class Meta:
        model = DonationItem
        fields = ['item_id', 'condition_rating', 'weight_kg', 'lookup_details']


class DonationUserSerializer(serializers.ModelSerializer):
    """Minimal user data for nesting in donations."""
    upload = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['user_id', 'email', 'role', 'first_name', 'last_name', 'business_name', 'contact_no', 'upload']

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


class DonationSerializer(serializers.ModelSerializer):
    donor = DonationUserSerializer(read_only=True)
    claimed_by_tuab = DonationUserSerializer(read_only=True)
    items = DonationItemSerializer(many=True, read_only=True)
    upload = serializers.SerializerMethodField()
    pickup_latitude = serializers.DecimalField(max_digits=18, decimal_places=15, read_only=True)
    pickup_longitude = serializers.DecimalField(max_digits=18, decimal_places=15, read_only=True)

    class Meta:
        model = Donation
        fields = '__all__'

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


class DonationCreateSerializer(serializers.Serializer):
    donor_user_id = serializers.IntegerField(required=False, allow_null=True)
    items = serializers.CharField()  # JSON string from multipart/form-data
    donation_image = serializers.ImageField(required=False, allow_null=True)
    preferred_pickup_date = serializers.DateTimeField()
    preferred_pickup_window_start = serializers.TimeField()
    preferred_pickup_window_end = serializers.TimeField()
    pickup_display_address = serializers.CharField(max_length=255)
    pickup_latitude = serializers.DecimalField(max_digits=18, decimal_places=15)
    pickup_longitude = serializers.DecimalField(max_digits=18, decimal_places=15)

    def validate(self, data):
        request = self.context.get('request')
        errors = {}

        # 1. Image Validation (Format & Size)
        image = data.get('donation_image')
        if image:
            if image.size > 5 * 1024 * 1024:
                errors['donation_image'] = "Image size must not exceed 5MB."
            import os
            if os.path.splitext(image.name)[1].lower() not in ['.jpg', '.jpeg', '.png']:
                errors['donation_image'] = "Only .jpg, .jpeg, and .png images are allowed."

        # 2. Coordinate Precision & Location Check (NCR only)
        lat = data.get('pickup_latitude')
        lng = data.get('pickup_longitude')
        if request:
            for field, val in [('pickup_latitude', lat), ('pickup_longitude', lng)]:
                raw_val = request.data.get(field)
                if raw_val and not re.match(r'^-?\d+\.\d{7}$', str(raw_val)):
                    errors[field] = "Must have exactly 7 decimal places (e.g., 14.1234567)."

        if lat is not None and lng is not None and 'pickup_latitude' not in errors:
            loc = get_city_and_barangay(lat, lng)
            if not loc:
                errors['pickup_latitude'] = "Pickup location must be within the National Capital Region (NCR)."
            else:
                data['_loc_barangay'] = loc['barangay']
                data['_loc_city'] = loc['city']

        # 3. Date & Time Validation
        now_local = timezone.localtime(timezone.now())
        pick_date = data.get('preferred_pickup_date')
        if pick_date:
            pick_date_local = timezone.localtime(pick_date)
            win_start = data.get('preferred_pickup_window_start')
            win_end = data.get('preferred_pickup_window_end')

            if pick_date_local.date() < now_local.date():
                errors['preferred_pickup_date'] = "Pickup date cannot be in the past."
            elif pick_date_local.date() > (now_local + timedelta(days=29)).date():
                errors['preferred_pickup_date'] = "Pickup date cannot be more than 29 days into the future."
            elif pick_date_local.date() == now_local.date() and win_start and win_start < now_local.time():
                errors['preferred_pickup_window_start'] = "Pickup window start time cannot be in the past for today's pickup."

            if win_start and win_end and win_start >= win_end:
                errors['preferred_pickup_window_start'] = "Start time must be before end time."

        # 4. Donor Status & Identity Validation
        donor_id = data.get('donor_user_id')
        if not donor_id:
            if request and request.user.role == UserRole.DONOR:
                donor_id = request.user.user_id
                data['donor_user_id'] = donor_id
            else:
                errors['donor_user_id'] = "This field is required for admins."

        if donor_id and 'donor_user_id' not in errors:
            donor = User.objects.filter(pk=donor_id).first()
            if not donor:
                errors['donor_user_id'] = "User does not exist."
            elif donor.role != UserRole.DONOR:
                errors['donor_user_id'] = "Selected user is not a donor."
            elif donor.status != UserAccountStatus.ACTIVE:
                errors['donor_user_id'] = "Donation can only be created for ACTIVE donors."
            elif request and request.user.role == UserRole.DONOR and donor_id != request.user.user_id:
                errors['donor_user_id'] = "Donors can only create donations for themselves."

        # 6. Items Parsing & DB Validation
        try:
            items = json.loads(data.get('items'))
            if not isinstance(items, list) or not items:
                errors['items'] = "Items must be a non-empty list."
            else:
                lookup_ids = [i.get('lookup_id') for i in items if i.get('lookup_id')]
                existing_ids = set(BrandFiberLookup.objects.filter(lookup_id__in=lookup_ids, is_active=True).values_list('lookup_id', flat=True))
                for i in items:
                    if any(k not in i for k in ['lookup_id', 'weight_kg', 'condition_rating']):
                        errors['items'] = "Each item must have lookup_id, weight_kg, and condition_rating."
                        break
                    if i['lookup_id'] not in existing_ids:
                        errors['items'] = f"Lookup ID {i['lookup_id']} does not exist."
                        break
                    if float(i['weight_kg']) <= 0:
                        errors['items'] = "Weight must be greater than 0."
                        break
                data['items'] = items # Replace string with parsed list
        except (json.JSONDecodeError, ValueError, TypeError):
            errors['items'] = "Invalid format for items."

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def create(self, validated_data):
        # We pop items here because they will be created by the service layer
        validated_data.pop('items', None)
        image_file = validated_data.pop('donation_image', None)
        donor_id = validated_data.get('donor_user_id')

        # 1. Identity
        donor = User.objects.get(pk=donor_id)

        # 2. Location Resolution (already checked in validate)
        barangay = validated_data.get('_loc_barangay', 'Unknown')
        city = validated_data.get('_loc_city', 'Unknown')

        # 3. Image Handling
        upload_obj = None
        if image_file:
            try:
                # Open image and optimize
                img = Image.open(image_file)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Resize to max 1024x1024 while maintaining aspect ratio
                img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                
                # Save optimized version to buffer
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=65, optimize=True)
                buffer.seek(0)
                
                # Prepare filename (ensure .jpg extension)
                base_name = f"don_{donor.user_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
                optimized_filename = f"{base_name}.jpg"
                optimized_file = ContentFile(buffer.read(), name=optimized_filename)
                
                # Save to storage
                path = default_storage.save(f"donations/{optimized_filename}", optimized_file)
                upload_obj = Upload.objects.create(file_path=path, name=optimized_filename[:50])
            except Exception:
                # Fallback to original if processing fails
                ext = os.path.splitext(image_file.name)[1]
                base_name = f"don_{donor.user_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
                safe_name = (base_name[:50-len(ext)] + ext) if len(base_name + ext) > 50 else (base_name + ext)
                path = default_storage.save(f"donations/{safe_name}", image_file)
                upload_obj = Upload.objects.create(file_path=path, name=safe_name)

        # 4. Create Donation (Header Only)
        donation = Donation.objects.create(
            donor=donor,
            upload=upload_obj,
            status=DonationStatus.PENDING,
            auto_archive_at=timezone.now() + timedelta(days=30),
            pickup_barangay=barangay,
            pickup_city=city,
            pickup_display_address=validated_data.get('pickup_display_address'),
            pickup_latitude=validated_data.get('pickup_latitude'),
            pickup_longitude=validated_data.get('pickup_longitude'),
            preferred_pickup_date=validated_data.get('preferred_pickup_date'),
            preferred_pickup_window_start=validated_data.get('preferred_pickup_window_start'),
            preferred_pickup_window_end=validated_data.get('preferred_pickup_window_end'),
        )

        return donation

class QuotationRequestSerializer(serializers.ModelSerializer):
    dropoff_address = serializers.CharField(source='dropoff_display_address', max_length=200)
    dropoff_lat = serializers.DecimalField(source='dropoff_latitude', max_digits=18, decimal_places=15)
    dropoff_lng = serializers.DecimalField(source='dropoff_longitude', max_digits=18, decimal_places=15)
    scheduled_time = serializers.TimeField(input_formats=['%H:%M', '%H:%M:%S'])

    class Meta:
        model = Order
        fields = ['dropoff_address', 'dropoff_lat', 'dropoff_lng', 'scheduled_time']

    def validate_dropoff_address(self, value):
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("Address cannot be empty or just whitespace.")
        return stripped

    def validate(self, data):
        lat = data.get('dropoff_latitude')
        lng = data.get('dropoff_longitude')
        scheduled_time = data.get('scheduled_time')
        donation = self.context.get('donation')
        
        # 1. 7-Decimal Precision Enforcement
        request = self.context.get('request')
        if request:
            import re
            for field in ['dropoff_lat', 'dropoff_lng']:
                raw_val = request.data.get(field)
                if raw_val and not re.match(r'^-?\d+\.\d{7}$', str(raw_val)):
                    raise serializers.ValidationError({field: "Must have exactly 7 decimal places (e.g., 14.1234567)."})

        # 2. NCR Geofencing
        location_info = get_city_and_barangay(lat, lng)
        if not location_info:
            raise serializers.ValidationError({
                "dropoff_lat": "Delivery address must be within Metro Manila (NCR)."
            })

        if donation and scheduled_time:
            window_start = donation.preferred_pickup_window_start
            window_end = donation.preferred_pickup_window_end

            if scheduled_time < window_start or scheduled_time > window_end:
                raise serializers.ValidationError({
                    "scheduled_time": "Scheduled time must be within the donation's preferred pickup window."
                })

            # --- MANILA-FIRST LOCALIZATION ---
            # 1. Convert the UTC date to Manila local time
            # 2. Replace the hours/minutes with the user's selected window
            scheduled_at = timezone.localtime(donation.preferred_pickup_date).replace(
                hour=scheduled_time.hour,
                minute=scheduled_time.minute,
                second=scheduled_time.second,
                microsecond=0,
            )
            # No need for make_aware, localtime already returned an aware object

            if scheduled_at < timezone.now():
                raise serializers.ValidationError({
                    "scheduled_time": "Scheduled time cannot be in the past."
                })
            
        return data
