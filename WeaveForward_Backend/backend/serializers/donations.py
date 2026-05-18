import re
import json
import os
from decimal import Decimal
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
    items = serializers.SerializerMethodField()
    upload = serializers.SerializerMethodField()
    pickup_latitude = serializers.DecimalField(max_digits=9, decimal_places=7, read_only=True)
    pickup_longitude = serializers.DecimalField(max_digits=10, decimal_places=7, read_only=True)

    class Meta:
        model = Donation
        fields = '__all__'

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)

    def get_items(self, obj):
        active_items = obj.items.filter(is_archived=False)
        return DonationItemSerializer(active_items, many=True, context=self.context).data


class DonationCreateSerializer(serializers.ModelSerializer):
    donor_user_id = serializers.IntegerField(required=False, allow_null=True)
    items = serializers.CharField(write_only=True)  # JSON string from multipart/form-data
    donation_image = serializers.ImageField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = Donation
        fields = [
            'donor_user_id', 'items', 'donation_image',
            'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end',
            'pickup_display_address', 'pickup_latitude', 'pickup_longitude'
        ]

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
        items_raw = data.get('items')
        if not items_raw:
            errors['items'] = "This field is required."
        else:
            try:
                items = json.loads(items_raw)
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
        # 1. Pop non-model fields
        validated_data.pop('items', None)
        validated_data.pop('donation_image', None)
        donor_id = validated_data.pop('donor_user_id')

        # 2. Add derived & default fields
        validated_data.update({
            'donor': User.objects.get(pk=donor_id),
            'status': DonationStatus.PENDING,
            'auto_archive_at': timezone.now() + timedelta(days=30),
            'pickup_barangay': validated_data.pop('_loc_barangay', 'Unknown'),
            'pickup_city': validated_data.pop('_loc_city', 'Unknown'),
        })

        # 3. Leverage ModelSerializer to handle the rest (lat, lng, address, upload, etc.)
        return super().create(validated_data)


class QuotationRequestSerializer(serializers.ModelSerializer):
    dropoff_address = serializers.CharField(source='dropoff_display_address', max_length=200)
    dropoff_lat = serializers.DecimalField(source='dropoff_latitude', max_digits=9, decimal_places=7)
    dropoff_lng = serializers.DecimalField(source='dropoff_longitude', max_digits=10, decimal_places=7)
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



class DonationItemUpdateSerializer(serializers.ModelSerializer):
    """Internal serializer to validate individual item updates."""
    item_id = serializers.IntegerField(required=False)
    is_archived = serializers.BooleanField(default=False)

    class Meta:
        model = DonationItem
        fields = ['item_id', 'lookup', 'weight_kg', 'condition_rating', 'is_archived']
        extra_kwargs = {
            'lookup': {'required': False},
            'weight_kg': {'min_value': Decimal('0.01'), 'required': False},
            'condition_rating': {'required': False},
        }

    def validate(self, data):
        item_id = data.get('item_id')
        is_archived = data.get('is_archived', False)
        print(f"\n>>> [DEBUG] ITEM {item_id} INITIAL_DATA: {self.initial_data}\n")
        
        # 1. REMOVING (Archive Case)
        if is_archived:
            if not item_id:
                raise serializers.ValidationError("item_id is required to remove an item.")
            return data

        # 2. ADDING (New Item Case)
        if not item_id:
            if not data.get('lookup') or not data.get('weight_kg') or not data.get('condition_rating'):
                raise serializers.ValidationError("New items require: lookup_id, weight_kg, and condition_rating.")
            return data
        
        # 3. EDITING (Update Case)
        # Ensure at least one of the fields is provided in the validated data
        update_fields = {'lookup', 'weight_kg', 'condition_rating'}
        if not any(f in data for f in update_fields):
            raise serializers.ValidationError(f"Update for item {item_id} must provide at least one field to change.")

        return data


class DonorDonationUpdateSerializer(serializers.ModelSerializer):
    """Specific serializer for Donors to update their PENDING donations."""
    items = serializers.CharField(required=False)  # JSON string
    donation_image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Donation
        fields = [
            'pickup_display_address', 'pickup_latitude', 'pickup_longitude',
            'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end',
            'items', 'donation_image'
        ]
        extra_kwargs = {
            'pickup_latitude': {'required': False},
            'pickup_longitude': {'required': False},
            'preferred_pickup_date': {'required': False},
            'preferred_pickup_window_start': {'required': False},
            'preferred_pickup_window_end': {'required': False},
            'pickup_display_address': {'required': False},
        }

    def update(self, instance, validated_data):
        # 1. Pop non-model fields (items handled by service)
        validated_data.pop('items', None)
        
        # 2. Update model fields automatically
        # (donation_image handled by Service)
        validated_data.pop('donation_image', None)

        # 3. Update remaining model fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance

    def validate(self, data):
        request = self.context.get('request')
        errors = {}

        # 1. Image Validation
        image = data.get('donation_image')
        if image:
            if image.size > 5 * 1024 * 1024:
                errors['donation_image'] = "Image size must not exceed 5MB."
            if os.path.splitext(image.name)[1].lower() not in ['.jpg', '.jpeg', '.png']:
                errors['donation_image'] = "Only .jpg, .jpeg, and .png images are allowed."

        # 2. Location Validation
        lat = data.get('pickup_latitude')
        lng = data.get('pickup_longitude')
        if lat is not None or lng is not None:
            if lat is not None and lng is not None:
                if request:
                    for field, val in [('pickup_latitude', lat), ('pickup_longitude', lng)]:
                        raw_val = request.data.get(field)
                        if raw_val and not re.match(r'^-?\d+\.\d{7}$', str(raw_val)):
                            errors[field] = "Must have exactly 7 decimal places (e.g., 14.1234567)."

                if 'pickup_latitude' not in errors:
                    loc = get_city_and_barangay(lat, lng)
                    if not loc:
                        errors['pickup_latitude'] = "Pickup location must be within the National Capital Region (NCR)."
                    else:
                        data['pickup_barangay'] = loc['barangay']
                        data['pickup_city'] = loc['city']
            else:
                errors['pickup_latitude'] = "Both latitude and longitude are required for location updates."

        # 3. Date & Time Validation
        now_local = timezone.localtime(timezone.now())
        pick_date = data.get('preferred_pickup_date') or self.instance.preferred_pickup_date
        win_start = data.get('preferred_pickup_window_start') or self.instance.preferred_pickup_window_start
        win_end = data.get('preferred_pickup_window_end') or self.instance.preferred_pickup_window_end

        if pick_date:
            pick_date_local = timezone.localtime(pick_date)
            if pick_date_local.date() < now_local.date():
                errors['preferred_pickup_date'] = "Pickup date cannot be in the past."
            elif pick_date_local.date() > (now_local + timedelta(days=29)).date():
                errors['preferred_pickup_date'] = "Pickup date cannot be more than 29 days into the future."
            
            # Additional check: Today's pickup window cannot start in the past
            if pick_date_local.date() == now_local.date() and win_start and win_start < now_local.time():
                errors['preferred_pickup_window_start'] = "Pickup window start time cannot be in the past for today's pickup."

        if win_start and win_end and win_start >= win_end:
            errors['preferred_pickup_window_start'] = "Start time must be before end time."

        # 4. Items Parsing & Validation (Simplified via nested serializer)
        items_json = data.get('items')
        if items_json:
            try:
                raw_items = json.loads(items_json)
                item_serializer = DonationItemUpdateSerializer(data=raw_items, many=True)
                item_serializer.is_valid(raise_exception=True)
                items = item_serializer.validated_data

                # Ownership check (Security)
                existing_item_ids = set(self.instance.items.values_list('item_id', flat=True))
                for i in items:
                    if i.get('item_id') and i['item_id'] not in existing_item_ids:
                        raise serializers.ValidationError({"items": f"Item {i['item_id']} does not belong to this donation."})
                
                # Rule: At least one active item must remain
                active_items_count = self.instance.items.filter(is_archived=False).count()
                num_archiving = len([i for i in items if i.get('is_archived') and i.get('item_id')])
                num_adding = len([i for i in items if not i.get('item_id') and not i.get('is_archived')])
                
                if (active_items_count - num_archiving + num_adding) < 1:
                    raise serializers.ValidationError("A donation must have at least one active clothing group.")

                data['items'] = items

            except (json.JSONDecodeError, ValueError, TypeError):
                errors['items'] = "Invalid format for items."
            except serializers.ValidationError as e:
                errors['items'] = e.detail

        if errors:
            raise serializers.ValidationError(errors)

        return data
