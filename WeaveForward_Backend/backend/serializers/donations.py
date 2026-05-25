import re
import json
import os
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date, parse_time
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from rest_framework import serializers

from ..models import (
    BrandFiberLookup, Donation, DonationItem, Upload, User, 
    UserAccountStatus, UserRole, DonationStatus, DonationItemConditionRating, Order,
    DonationDeliveryMethod
)
from ..services.location_service import get_city_and_barangay
from ..services.upload_service import build_upload_url


from .brandfiberlookups import BrandFiberLookupSerializer



# ------------------------------------------------------------------------------
# ## Read-Only Serializers
# ------------------------------------------------------------------------------

class DonationListLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandFiberLookup
        fields = ['clothing_type', 'brand', 'dominant_fiber']

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if ret.get('clothing_type'):
            ret['clothing_type'] = ret['clothing_type'].capitalize()
        return ret


class DonationListItemSerializer(serializers.ModelSerializer):
    lookup_details = DonationListLookupSerializer(source='lookup', read_only=True)

    class Meta:
        model = DonationItem
        fields = ['lookup_details']

class DonationListDonorSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['user_id', 'first_name', 'last_name']


class DonationListClaimedBySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['user_id', 'business_name']


class DonationListSerializer(serializers.ModelSerializer):
    donor = DonationListDonorSerializer(read_only=True)
    claimed_by_tuab = DonationListClaimedBySerializer(read_only=True)
    items = DonationListItemSerializer(source='active_items', many=True, read_only=True)
    upload = serializers.SerializerMethodField()
    pickup_latitude = serializers.DecimalField(max_digits=9, decimal_places=7, read_only=True)
    pickup_longitude = serializers.DecimalField(max_digits=10, decimal_places=7, read_only=True)

    class Meta:
        model = Donation
        fields = [
            'donation_id',
            'donor',
            'claimed_by_tuab',
            'items',
            'upload',
            'status',
            'is_flagged',
            'delivery_method',
            'pickup_display_address',
            'pickup_latitude',
            'pickup_longitude',
            'preferred_pickup_date',
            'preferred_pickup_window_start',
            'preferred_pickup_window_end',
        ]

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)

class DonationDetailItemSerializer(serializers.ModelSerializer):
    lookup_details = BrandFiberLookupSerializer(source='lookup', read_only=True)

    class Meta:
        model = DonationItem
        fields = ['item_id', 'condition_rating', 'weight_kg', 'lookup_details']


class DonationDetailUserSerializer(serializers.ModelSerializer):
    """Minimal user data for nesting in donations."""
    upload = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['user_id', 'email', 'role', 'first_name', 'last_name', 'business_name', 'contact_no', 'upload']

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.role == 'TUAB':
            data.pop('first_name', None)
            data.pop('last_name', None)
        elif instance.role == 'Donor':
            data.pop('business_name', None)
        return data
    
class DonationDetailSerializer(serializers.ModelSerializer):
    donor = DonationDetailUserSerializer(read_only=True)
    claimed_by_tuab = DonationDetailUserSerializer(read_only=True)
    items = DonationDetailItemSerializer(source='active_items', many=True, read_only=True)
    upload = serializers.SerializerMethodField()
    pickup_latitude = serializers.DecimalField(max_digits=9, decimal_places=7, read_only=True)
    pickup_longitude = serializers.DecimalField(max_digits=10, decimal_places=7, read_only=True)
    dropoff_display_address = serializers.SerializerMethodField()
    dropoff_latitude = serializers.SerializerMethodField()
    dropoff_longitude = serializers.SerializerMethodField()

    class Meta:
        model = Donation
        fields = '__all__'

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)

    def get_dropoff_display_address(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.role == 'Admin':
            order = obj.orders.first()
            return order.dropoff_display_address if order else None
        return None

    def get_dropoff_latitude(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.role == 'Admin':
            order = obj.orders.first()
            return order.dropoff_latitude if order else None
        return None

    def get_dropoff_longitude(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.role == 'Admin':
            order = obj.orders.first()
            return order.dropoff_longitude if order else None
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if not request or not request.user or request.user.role != 'Admin':
            data.pop('dropoff_display_address', None)
            data.pop('dropoff_latitude', None)
            data.pop('dropoff_longitude', None)
        return data


# ------------------------------------------------------------------------------
# ## Create-Only Serializer
# ------------------------------------------------------------------------------
class DonationCreateSerializer(serializers.ModelSerializer):
    donor_user_id = serializers.IntegerField(required=False, allow_null=True)
    items = serializers.CharField(required=False, allow_null=True, allow_blank=True, write_only=True)  # JSON string from multipart/form-data
    donation_image = serializers.ImageField(required=False, allow_null=True, write_only=True)

    preferred_pickup_date = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    preferred_pickup_window_start = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    preferred_pickup_window_end = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    pickup_latitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    pickup_longitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    pickup_display_address = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = Donation
        fields = [
            'donor_user_id', 'items', 'donation_image',
            'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end',
            'pickup_display_address', 'pickup_latitude', 'pickup_longitude'
        ]
        extra_kwargs = {
            'pickup_latitude': {'required': False, 'allow_null': True},
            'pickup_longitude': {'required': False, 'allow_null': True},
            'preferred_pickup_date': {'required': False, 'allow_null': True},
            'preferred_pickup_window_start': {'required': False, 'allow_null': True},
            'preferred_pickup_window_end': {'required': False, 'allow_null': True},
            'pickup_display_address': {'required': False, 'allow_null': True, 'allow_blank': True},
        }

    def validate(self, data):
        request = self.context.get('request')
        errors = {}

        # 1. Image Validation (Format & Size)
        image = data.get('donation_image')
        if image:
            if image.size > 5 * 1024 * 1024:
                errors['donation_image'] = "Image size must not exceed 5MB."
            if os.path.splitext(image.name)[1].lower() not in ['.jpg', '.jpeg', '.png']:
                errors['donation_image'] = "Only .jpg, .jpeg, and .png images are allowed."

        # 2. Required Display Address
        pickup_display_address = (data.get('pickup_display_address') or '').strip()
        if not pickup_display_address:
            errors['pickup_display_address'] = "This field is required."

        # 3. Coordinate Precision & Location Check (NCR only)
        raw_lat = str(self.initial_data.get('pickup_latitude') or '').strip()
        raw_lng = str(self.initial_data.get('pickup_longitude') or '').strip()
        coord_error = False

        if not raw_lat or not raw_lng or raw_lat == 'None' or raw_lng == 'None':
            if not raw_lat or raw_lat == 'None':
                errors['pickup_latitude'] = "This field is required."
            if not raw_lng or raw_lng == 'None':
                errors['pickup_longitude'] = "This field is required."
            coord_error = True
        else:
            if not re.match(r'^-?\d+\.\d{7}$', raw_lat):
                errors['pickup_latitude'] = "Must have exactly 7 decimal places (e.g., 14.1234567)."
                coord_error = True
            if not re.match(r'^-?\d+\.\d{7}$', raw_lng):
                errors['pickup_longitude'] = "Must have exactly 7 decimal places (e.g., 14.1234567)."
                coord_error = True

        if not coord_error:
            try:
                lat = Decimal(raw_lat)
                lng = Decimal(raw_lng)
                loc = get_city_and_barangay(lat, lng)
                if not loc:
                    errors['pickup_latitude'] = "Pickup location must be within the National Capital Region (NCR)."
                else:
                    data['pickup_latitude'] = lat
                    data['pickup_longitude'] = lng
                    data['_loc_barangay'] = loc['barangay']
                    data['_loc_city'] = loc['city']
            except (ValueError, TypeError, ArithmeticError):
                errors['pickup_latitude'] = "Invalid coordinate format."

        # 4. Required Field Format & Null Checks on Dates & Times
        raw_date = data.get('preferred_pickup_date')
        raw_start = data.get('preferred_pickup_window_start')
        raw_end = data.get('preferred_pickup_window_end')

        parsed_date = None
        parsed_start = None
        parsed_end = None

        val_date = str(raw_date or '').strip()
        if not val_date or val_date == 'None':
            errors['preferred_pickup_date'] = "This field is required."
        else:
            try:
                parsed_date = parse_datetime(val_date)
                if parsed_date is not None and timezone.is_naive(parsed_date):
                    parsed_date = timezone.make_aware(parsed_date)
                if parsed_date is None:
                    d = parse_date(val_date)
                    if d:
                        parsed_date = timezone.make_aware(timezone.datetime.combine(d, timezone.datetime.min.time()))
                
                if parsed_date is None:
                    errors['preferred_pickup_date'] = "Datetime has wrong format."
                else:
                    data['preferred_pickup_date'] = parsed_date
            except Exception:
                errors['preferred_pickup_date'] = "Datetime has wrong format."

        val_start = str(raw_start or '').strip()
        if not val_start or val_start == 'None':
            errors['preferred_pickup_window_start'] = "This field is required."
        else:
            try:
                parsed_start = parse_time(val_start)
                if parsed_start is None:
                    errors['preferred_pickup_window_start'] = "Time has wrong format."
                else:
                    data['preferred_pickup_window_start'] = parsed_start
            except Exception:
                errors['preferred_pickup_window_start'] = "Time has wrong format."

        val_end = str(raw_end or '').strip()
        if not val_end or val_end == 'None':
            errors['preferred_pickup_window_end'] = "This field is required."
        else:
            try:
                parsed_end = parse_time(val_end)
                if parsed_end is None:
                    errors['preferred_pickup_window_end'] = "Time has wrong format."
                else:
                    data['preferred_pickup_window_end'] = parsed_end
            except Exception:
                errors['preferred_pickup_window_end'] = "Time has wrong format."

        # 5. Date & Time Validation
        pick_date = data.get('preferred_pickup_date')
        win_start = data.get('preferred_pickup_window_start')
        win_end = data.get('preferred_pickup_window_end')

        if 'preferred_pickup_date' not in errors and 'preferred_pickup_window_start' not in errors and 'preferred_pickup_window_end' not in errors:
            if pick_date:
                now_local = timezone.localtime(timezone.now())
                try:
                    if isinstance(pick_date, timezone.datetime) and timezone.is_naive(pick_date):
                        pick_date = timezone.make_aware(pick_date)
                    pick_date_local = timezone.localtime(pick_date)
                    if pick_date_local.date() < now_local.date():
                        errors['preferred_pickup_date'] = "Pickup date cannot be in the past."
                    elif pick_date_local.date() > (now_local + timedelta(days=29)).date():
                        errors['preferred_pickup_date'] = "Pickup date cannot be more than 29 days into the future."
                    elif pick_date_local.date() == now_local.date() and win_start and win_start < now_local.time():
                        errors['preferred_pickup_window_start'] = "Pickup window start time cannot be in the past for today's pickup."
                except Exception:
                    pass

            if win_start and win_end and win_start >= win_end:
                errors['preferred_pickup_window_start'] = "Start time must be before end time."

        # 6. Donor Status & Identity Validation
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

        # 7. Items Parsing & DB Validation
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


# ------------------------------------------------------------------------------
# ## Quotation Request Serializer
# ------------------------------------------------------------------------------
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



# ------------------------------------------------------------------------------
# ## Update-Only Serializers
# ------------------------------------------------------------------------------
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

    preferred_pickup_date = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    preferred_pickup_window_start = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    preferred_pickup_window_end = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    pickup_latitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    pickup_longitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    pickup_display_address = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = Donation
        fields = [
            'pickup_display_address', 'pickup_latitude', 'pickup_longitude',
            'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end',
            'items', 'donation_image'
        ]
        extra_kwargs = {
            'pickup_latitude': {'required': False, 'allow_null': True},
            'pickup_longitude': {'required': False, 'allow_null': True},
            'preferred_pickup_date': {'required': False, 'allow_null': True},
            'preferred_pickup_window_start': {'required': False, 'allow_null': True},
            'preferred_pickup_window_end': {'required': False, 'allow_null': True},
            'pickup_display_address': {'required': False, 'allow_null': True, 'allow_blank': True},
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

        # 2. Address Validation
        if 'pickup_display_address' in data:
            pickup_display_address = (data.get('pickup_display_address') or '').strip()
            if not pickup_display_address:
                errors['pickup_display_address'] = "This field may not be blank."

        # 3. Location Validation
        if 'pickup_latitude' in data or 'pickup_longitude' in data:
            if 'pickup_display_address' not in data or not (data.get('pickup_display_address') or '').strip():
                errors['pickup_display_address'] = "This field is required when updating coordinates."

            raw_lat = str(self.initial_data.get('pickup_latitude') or '').strip()
            raw_lng = str(self.initial_data.get('pickup_longitude') or '').strip()

            if not raw_lat or not raw_lng or raw_lat == 'None' or raw_lng == 'None':
                errors['pickup_latitude'] = "This field may not be null."
                errors['pickup_longitude'] = "This field may not be null."
            else:
                coord_error = False
                if not re.match(r'^-?\d+\.\d{7}$', raw_lat):
                    errors['pickup_latitude'] = "Must have exactly 7 decimal places (e.g., 14.1234567)."
                    coord_error = True
                if not re.match(r'^-?\d+\.\d{7}$', raw_lng):
                    errors['pickup_longitude'] = "Must have exactly 7 decimal places (e.g., 14.1234567)."
                    coord_error = True

                if not coord_error:
                    try:
                        lat_dec = Decimal(raw_lat)
                        lng_dec = Decimal(raw_lng)
                        loc = get_city_and_barangay(lat_dec, lng_dec)
                        if not loc:
                            errors['pickup_latitude'] = "Pickup location must be within the National Capital Region (NCR)."
                        else:
                            data['pickup_latitude'] = lat_dec
                            data['pickup_longitude'] = lng_dec
                            data['pickup_barangay'] = loc['barangay']
                            data['pickup_city'] = loc['city']
                    except (ValueError, TypeError, ArithmeticError):
                        errors['pickup_latitude'] = "Invalid coordinate format."

        # 4. Required Field Null / Format Checks on Dates & Times
        if 'preferred_pickup_date' in data:
            raw_date = data.get('preferred_pickup_date')
            val_date = str(raw_date or '').strip()
            if not val_date or val_date == 'None':
                errors['preferred_pickup_date'] = "This field may not be null."
            else:
                try:
                    parsed_date = parse_datetime(val_date)
                    if parsed_date is not None and timezone.is_naive(parsed_date):
                        parsed_date = timezone.make_aware(parsed_date)
                    if parsed_date is None:
                        d = parse_date(val_date)
                        if d:
                            parsed_date = timezone.make_aware(timezone.datetime.combine(d, timezone.datetime.min.time()))
                    
                    if parsed_date is None:
                        errors['preferred_pickup_date'] = "Datetime has wrong format."
                    else:
                        data['preferred_pickup_date'] = parsed_date
                except Exception:
                    errors['preferred_pickup_date'] = "Datetime has wrong format."

        if 'preferred_pickup_window_start' in data:
            raw_start = data.get('preferred_pickup_window_start')
            val_start = str(raw_start or '').strip()
            if not val_start or val_start == 'None':
                errors['preferred_pickup_window_start'] = "This field may not be null."
            else:
                try:
                    parsed_start = parse_time(val_start)
                    if parsed_start is None:
                        errors['preferred_pickup_window_start'] = "Time has wrong format."
                    else:
                        data['preferred_pickup_window_start'] = parsed_start
                except Exception:
                    errors['preferred_pickup_window_start'] = "Time has wrong format."

        if 'preferred_pickup_window_end' in data:
            raw_end = data.get('preferred_pickup_window_end')
            val_end = str(raw_end or '').strip()
            if not val_end or val_end == 'None':
                errors['preferred_pickup_window_end'] = "This field may not be null."
            else:
                try:
                    parsed_end = parse_time(val_end)
                    if parsed_end is None:
                        errors['preferred_pickup_window_end'] = "Time has wrong format."
                    else:
                        data['preferred_pickup_window_end'] = parsed_end
                except Exception:
                    errors['preferred_pickup_window_end'] = "Time has wrong format."

        # 5. Date & Time Validation
        now_local = timezone.localtime(timezone.now())
        pick_date = data.get('preferred_pickup_date') if 'preferred_pickup_date' in data else self.instance.preferred_pickup_date
        win_start = data.get('preferred_pickup_window_start') if 'preferred_pickup_window_start' in data else self.instance.preferred_pickup_window_start
        win_end = data.get('preferred_pickup_window_end') if 'preferred_pickup_window_end' in data else self.instance.preferred_pickup_window_end

        if 'preferred_pickup_date' not in errors and 'preferred_pickup_window_start' not in errors and 'preferred_pickup_window_end' not in errors:
            if pick_date:
                try:
                    if isinstance(pick_date, timezone.datetime) and timezone.is_naive(pick_date):
                        pick_date = timezone.make_aware(pick_date)
                    pick_date_local = timezone.localtime(pick_date)
                    if pick_date_local.date() < now_local.date():
                        errors['preferred_pickup_date'] = "Pickup date cannot be in the past."
                    elif pick_date_local.date() > (now_local + timedelta(days=29)).date():
                        errors['preferred_pickup_date'] = "Pickup date cannot be more than 29 days into the future."
                    
                    # Additional check: Today's pickup window cannot start in the past
                    if pick_date_local.date() == now_local.date() and win_start and win_start < now_local.time():
                        errors['preferred_pickup_window_start'] = "Pickup window start time cannot be in the past for today's pickup."
                except Exception:
                    pass

            if win_start and win_end and win_start >= win_end:
                errors['preferred_pickup_window_start'] = "Start time must be before end time."

        # 6. Items Parsing & Validation (Simplified via nested serializer)
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


class DonationResolveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[DonationStatus.RECEIVED, DonationStatus.REJECTED])
    rejection_reason = serializers.CharField(required=False, allow_blank=True, max_length=200)
    items = serializers.CharField(required=False)

    def validate(self, data):
        status = data.get('status')
        rejection_reason = data.get('rejection_reason')
        items_json = data.get('items')
        errors = {}

        if status == DonationStatus.REJECTED:
            if not rejection_reason or not rejection_reason.strip():
                errors['rejection_reason'] = "Rejection reason is required when status is REJECTED."
        
        if items_json:
            try:
                raw_items = json.loads(items_json)
                item_serializer = DonationItemUpdateSerializer(data=raw_items, many=True)
                item_serializer.is_valid(raise_exception=True)
                items = item_serializer.validated_data

                # Ownership check (Security)
                donation = self.context.get('donation')
                if donation:
                    existing_item_ids = set(donation.items.values_list('item_id', flat=True))
                    for i in items:
                        if i.get('item_id') and i['item_id'] not in existing_item_ids:
                            raise serializers.ValidationError({"items": f"Item {i['item_id']} does not belong to this donation."})
                    
                    # Rule: At least one active item must remain
                    active_items_count = donation.items.filter(is_archived=False).count()
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


class AdminDonationUpdateSerializer(serializers.ModelSerializer):
    """Specific serializer for Admins to update donations and nested donation items."""
    items = serializers.CharField(required=False)  # JSON string for items
    donation_image = serializers.ImageField(required=False, allow_null=True)

    # Optional fields for dropoff location (associated Order fields)
    dropoff_display_address = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    dropoff_latitude = serializers.DecimalField(required=False, max_digits=18, decimal_places=15, allow_null=True)
    dropoff_longitude = serializers.DecimalField(required=False, max_digits=18, decimal_places=15, allow_null=True)

    class Meta:
        model = Donation
        fields = [
            'is_flagged', 'auto_archive_at',
            'pickup_display_address', 'pickup_latitude', 'pickup_longitude',
            'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end',
            'items', 'donation_image', 'dropoff_display_address', 'dropoff_latitude', 'dropoff_longitude'
        ]

    def validate(self, data):
        if not self.instance:
            return data

        errors = {}
        current_delivery_method = self.instance.delivery_method
        current_status = self.instance.status

        # 0. Image Validation (consistent with Donor restrictions)
        image = data.get('donation_image')
        if image:
            if image.size > 5 * 1024 * 1024:
                errors['donation_image'] = "Image size must not exceed 5MB."
            if os.path.splitext(image.name)[1].lower() not in ['.jpg', '.jpeg', '.png']:
                errors['donation_image'] = "Only .jpg, .jpeg, and .png images are allowed."
        if 'auto_archive_at' in data and data['auto_archive_at'] and data['auto_archive_at'] < timezone.now(): errors['auto_archive_at'] = "Auto archive cannot be earlier than today."

        # 1. State-based Lock Validation
        # Rules:
        # - If status is CLAIMED:
        #   Locked fields: The pickup details (pickup_display_address, pickup_latitude,
        #   pickup_longitude, preferred_pickup_date, preferred_pickup_window_start,
        #   preferred_pickup_window_end) cannot be changed.
        # - If status is IN_TRANSIT, RECEIVED, or REJECTED:
        #   Locked fields: The pickup details (above) cannot be changed.
        #   Locked fields: The dropoff details (dropoff_display_address, dropoff_latitude,
        #   dropoff_longitude) cannot be changed.
        if current_delivery_method == DonationDeliveryMethod.DELIVERY:
            if current_status == DonationStatus.CLAIMED:
                if intersecting := set(data.keys()).intersection({
                    'pickup_display_address', 'pickup_latitude', 'pickup_longitude',
                    'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end'
                }):
                    for field in intersecting:
                        if 'date' in field or 'window' in field:
                            errors[field] = "Cannot edit pickup date/time windows once the delivery has been claimed."
                        else:
                            errors[field] = "Cannot edit pickup location details once the delivery has been claimed."
            elif current_status in [DonationStatus.IN_TRANSIT, DonationStatus.RECEIVED, DonationStatus.REJECTED]:
                status_str = "in transit" if current_status == DonationStatus.IN_TRANSIT else current_status.lower()
                if intersecting_dropoff := set(data.keys()).intersection({
                    'dropoff_display_address', 'dropoff_latitude', 'dropoff_longitude'
                }):
                    for field in intersecting_dropoff:
                        errors[field] = f"Cannot edit dropoff location details once the delivery is {status_str}."
                
                if intersecting_pickup := set(data.keys()).intersection({
                    'pickup_display_address', 'pickup_latitude', 'pickup_longitude',
                    'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end'
                }):
                    for field in intersecting_pickup:
                        if 'date' in field or 'window' in field:
                            errors[field] = f"Cannot edit pickup date/time windows once the delivery is {status_str}."
                        else:
                            errors[field] = f"Cannot edit pickup location details once the delivery is {status_str}."

        # 2. Coordinate & Location Validation (only if they aren't blocked by state lock)
        if ('pickup_latitude' in data or 'pickup_longitude' in data) and 'pickup_latitude' not in errors and 'pickup_longitude' not in errors:
            if 'pickup_latitude' not in self.initial_data or 'pickup_longitude' not in self.initial_data:
                errors['pickup_latitude'] = "Both pickup_latitude and pickup_longitude are required to update coordinates."
            if 'pickup_display_address' not in data or not (data.get('pickup_display_address') or '').strip():
                errors['pickup_display_address'] = "This field is required when updating coordinates."

            if 'pickup_latitude' not in errors:
                raw_lat = str(self.initial_data.get('pickup_latitude') or '').strip()
                raw_lng = str(self.initial_data.get('pickup_longitude') or '').strip()

                coord_error = False
                if not re.match(r'^-?\d+\.\d{7}$', raw_lat):
                    errors['pickup_latitude'] = "Must have exactly 7 decimal places (e.g., 14.1234567)."
                    coord_error = True
                if not re.match(r'^-?\d+\.\d{7}$', raw_lng):
                    errors['pickup_longitude'] = "Must have exactly 7 decimal places (e.g., 14.1234567)."
                    coord_error = True

                if not coord_error:
                    try:
                        lat_dec = Decimal(raw_lat)
                        lng_dec = Decimal(raw_lng)
                        loc = get_city_and_barangay(lat_dec, lng_dec)
                        if not loc:
                            errors['pickup_latitude'] = "Pickup location must be within the National Capital Region (NCR)."
                        else:
                            data['pickup_barangay'] = loc['barangay']
                            data['pickup_city'] = loc['city']
                    except (ValueError, TypeError, ArithmeticError):
                        errors['pickup_latitude'] = "Invalid coordinate format."

        # 2.1 Dropoff Coordinate & Location Validation (only if they aren't blocked by state lock/delivery method)
        if current_delivery_method == DonationDeliveryMethod.PICKUP:
            for field in ['dropoff_display_address', 'dropoff_latitude', 'dropoff_longitude']:
                if field in data:
                    errors[field] = "Dropoff details are not allowed for PICKUP donations."
        elif ('dropoff_latitude' in data or 'dropoff_longitude' in data) and 'dropoff_latitude' not in errors and 'dropoff_longitude' not in errors:
            if 'dropoff_latitude' not in self.initial_data or 'dropoff_longitude' not in self.initial_data:
                errors['dropoff_latitude'] = "Both dropoff_latitude and dropoff_longitude are required to update coordinates."
            if 'dropoff_display_address' not in data or not (data.get('dropoff_display_address') or '').strip():
                errors['dropoff_display_address'] = "This field is required when updating coordinates."

            if 'dropoff_latitude' not in errors:
                raw_lat = str(self.initial_data.get('dropoff_latitude') or '').strip()
                raw_lng = str(self.initial_data.get('dropoff_longitude') or '').strip()

                coord_error = False
                if not re.match(r'^-?\d+\.\d{7}$', raw_lat):
                    errors['dropoff_latitude'] = "Must have exactly 7 decimal places (e.g., 14.1234567)."
                    coord_error = True
                if not re.match(r'^-?\d+\.\d{7}$', raw_lng):
                    errors['dropoff_longitude'] = "Must have exactly 7 decimal places (e.g., 14.1234567)."
                    coord_error = True

                if not coord_error:
                    try:
                        lat_dec = Decimal(raw_lat)
                        lng_dec = Decimal(raw_lng)
                        loc = get_city_and_barangay(lat_dec, lng_dec)
                        if not loc:
                            errors['dropoff_latitude'] = "Dropoff location must be within the National Capital Region (NCR)."
                    except (ValueError, TypeError, ArithmeticError):
                        errors['dropoff_latitude'] = "Invalid coordinate format."

        # 3. Date & Time Validation
        now_local = timezone.localtime(timezone.now())
        pick_date = data.get('preferred_pickup_date') if 'preferred_pickup_date' in data else self.instance.preferred_pickup_date
        win_start = data.get('preferred_pickup_window_start') if 'preferred_pickup_window_start' in data else self.instance.preferred_pickup_window_start
        win_end = data.get('preferred_pickup_window_end') if 'preferred_pickup_window_end' in data else self.instance.preferred_pickup_window_end

        if 'preferred_pickup_date' not in errors and 'preferred_pickup_window_start' not in errors and 'preferred_pickup_window_end' not in errors:
            if pick_date:
                try:
                    if isinstance(pick_date, timezone.datetime) and timezone.is_naive(pick_date):
                        pick_date = timezone.make_aware(pick_date)
                    pick_date_local = timezone.localtime(pick_date)
                    if pick_date_local.date() < now_local.date():
                        errors['preferred_pickup_date'] = "Pickup date cannot be in the past."
                    elif pick_date_local.date() > (now_local + timedelta(days=29)).date():
                        errors['preferred_pickup_date'] = "Pickup date cannot be more than 29 days into the future."
                    
                    # Additional check: Today's pickup window cannot start in the past
                    if pick_date_local.date() == now_local.date() and win_start and win_start < now_local.time():
                        errors['preferred_pickup_window_start'] = "Pickup window start time cannot be in the past for today's pickup."
                except Exception:
                    pass

            if win_start and win_end and win_start >= win_end:
                errors['preferred_pickup_window_start'] = "Start time must be before end time."

        # 4. Items validation (reusing items updates logic)
        items_json = data.get('items')
        if items_json:
            try:
                raw_items = json.loads(items_json)
                item_serializer = DonationItemUpdateSerializer(data=raw_items, many=True)
                if not item_serializer.is_valid():
                    errors['items'] = item_serializer.errors
                else:
                    items = item_serializer.validated_data

                    # Ownership check
                    existing_item_ids = set(self.instance.items.values_list('item_id', flat=True))
                    ownership_error = False
                    for i in items:
                        if i.get('item_id') and i['item_id'] not in existing_item_ids:
                            errors['items'] = f"Item {i['item_id']} does not belong to this donation."
                            ownership_error = True
                            break

                    if not ownership_error:
                        # Rule: At least one active item must remain
                        active_items_count = self.instance.items.filter(is_archived=False).count()
                        num_archiving = len([i for i in items if i.get('is_archived') and i.get('item_id')])
                        num_adding = len([i for i in items if not i.get('item_id') and not i.get('is_archived')])

                        if (active_items_count - num_archiving + num_adding) < 1:
                            errors['items'] = "A donation must have at least one active clothing group."
                        else:
                            data['items'] = items

            except (json.JSONDecodeError, ValueError, TypeError):
                errors['items'] = "Invalid format for items."

        if errors:
            raise serializers.ValidationError(errors)

        return data


