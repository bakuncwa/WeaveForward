import re
import json
import os
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone

from rest_framework import serializers

from ..models import (
    BrandFiberLookup, Donation, DonationItem, Upload, User, 
    UserAccountStatus, UserRole, DonationStatus, DonationItemConditionRating, Order,
    DonationDeliveryMethod
)
from ..services.location_service import get_city_and_barangay
from ..services.upload_service import build_upload_url
from ..services.lalamove_service import get_lalamove_order_driver, get_lalamove_driver_details


from .brandfiberlookups import BrandFiberLookupSerializer


# ------------------------------------------------------------------------------
# ## Read-Only Serializers
# ------------------------------------------------------------------------------

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
    items = serializers.SerializerMethodField()
    upload = serializers.SerializerMethodField()
    pickup_latitude = serializers.SerializerMethodField()
    pickup_longitude = serializers.SerializerMethodField()
    pickup_display_address = serializers.SerializerMethodField()

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

    def get_pickup_display_address(self, obj):
        request = self.context.get('request')
        view = self.context.get('view')
        user = getattr(request, 'user', None) if request else None
        if user and user.role == UserRole.ADMIN:
            return obj.pickup_display_address
        if view and view.action == 'list':
            return f"{obj.pickup_barangay}, {obj.pickup_city}"
        return obj.pickup_display_address

    def get_pickup_latitude(self, obj):
        request = self.context.get('request')
        view = self.context.get('view')
        user = getattr(request, 'user', None) if request else None
        if user and user.role == UserRole.ADMIN:
            return float(obj.pickup_latitude)
        if view and view.action == 'list':
            return round(float(obj.pickup_latitude), 2)
        return float(obj.pickup_latitude)

    def get_pickup_longitude(self, obj):
        request = self.context.get('request')
        view = self.context.get('view')
        user = getattr(request, 'user', None) if request else None
        if user and user.role == UserRole.ADMIN:
            return float(obj.pickup_longitude)
        if view and view.action == 'list':
            return round(float(obj.pickup_longitude), 2)
        return float(obj.pickup_longitude)

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)

    def get_items(self, obj):
        counts = {}
        for item in getattr(obj, 'active_items', []):
            if not item.lookup:
                continue
            fiber = (item.lookup.dominant_fiber or '').title()
            ctype = (item.lookup.clothing_type or '').title()
            name = f"{fiber} {ctype}" if fiber else ctype
            if name:
                counts[name] = counts.get(name, 0) + 1
        parts = []
        for name, count in counts.items():
            parts.append(f"{name} x{count}" if count > 1 else name)
        MAX_GROUPS = 8
        if len(parts) > MAX_GROUPS:
            parts = parts[:MAX_GROUPS] + [f"+{len(parts) - MAX_GROUPS} more"]
        return parts

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
    driver_details = serializers.SerializerMethodField()
    order_status = serializers.SerializerMethodField()
    pickup_display_address = serializers.SerializerMethodField()

    class Meta:
        model = Donation
        fields = '__all__'

    def get_pickup_display_address(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if user and user.role == UserRole.ADMIN:
            return obj.pickup_display_address
        if user and user.role == UserRole.TUAB and obj.status == DonationStatus.PENDING:
            return f"{obj.pickup_barangay}, {obj.pickup_city}"
        return obj.pickup_display_address

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)

    def _get_active_order(self, obj):
        return obj.orders.filter(status__in=['ASSIGNING_DRIVER', 'ON_GOING', 'PICKED_UP', 'CANCELLED']).first() or obj.orders.exclude(status__in=['FAILED']).first()

    def _get_latest_order(self, obj):
        return obj.orders.filter(
            lalamove_order_id__isnull=False
        ).order_by('-created_at').first()

    def _fetch_driver_details(self, order):
        if not order or not order.lalamove_order_id:
            return None
        order_result = get_lalamove_order_driver(order.lalamove_order_id)
        if "error" in order_result:
            return None
        driver_id = order_result.get("data", {}).get("driverId")
        if not driver_id:
            return None
        result = get_lalamove_driver_details(order.lalamove_order_id, driver_id)
        if "error" in result:
            return None
        return result.get("data")

    def get_dropoff_display_address(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.role == 'Admin':
            order = self._get_active_order(obj)
            return order.dropoff_display_address if order else None
        return None

    def get_dropoff_latitude(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.role == 'Admin':
            order = self._get_active_order(obj)
            return order.dropoff_latitude if order else None
        return None

    def get_dropoff_longitude(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.role == 'Admin':
            order = self._get_active_order(obj)
            return order.dropoff_longitude if order else None
        return None

    def get_driver_details(self, obj):
        request = self.context.get('request')
        if not request or not request.user or request.user.role not in ['TUAB', 'Admin']:
            return None
        order = obj.orders.filter(
            lalamove_order_id__isnull=False
        ).order_by('-created_at').first()
        return self._fetch_driver_details(order)

    def get_order_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user or request.user.role not in ['TUAB', 'Admin']:
            return None
        order = self._get_latest_order(obj)
        return order.status if order else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        role = request.user.role if request and request.user else None
        if role not in ('TUAB', 'Admin'):
            data.pop('driver_details', None)
            data.pop('order_status', None)
        if role != 'Admin':
            data.pop('dropoff_display_address', None)
            data.pop('dropoff_latitude', None)
            data.pop('dropoff_longitude', None)
        return data


# ------------------------------------------------------------------------------
# ## Create-Only Serializer
# ------------------------------------------------------------------------------
class DonationCreateSerializer(serializers.ModelSerializer):
    donor_user_id = serializers.IntegerField(required=False, allow_null=True)
    items = serializers.CharField(write_only=True)
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

        # 1. Image Validation
        image = data.get('donation_image')
        if image:
            valid_exts = ['.jpg', '.jpeg', '.png']
            if image.size > 5 * 1024 * 1024 or os.path.splitext(image.name)[1].lower() not in valid_exts:
                raise serializers.ValidationError({'donation_image': "Please upload a JPG or PNG image under 5 MB."})

        # 2. Coordinate & Location Check
        lat, lng = data['pickup_latitude'], data['pickup_longitude']
        try:
            loc = get_city_and_barangay(lat, lng)
            if not loc:
                raise ValueError
            data['_loc_barangay'] = loc['barangay']
            data['_loc_city'] = loc['city']
        except Exception:
            raise serializers.ValidationError({'pickup_location': "We couldn't find that location. Please make sure the pickup address is within Metro Manila."})

        # 3. Date & Time Business Rules
        pick_date = data.get('preferred_pickup_date')
        win_start = data.get('preferred_pickup_window_start')
        win_end = data.get('preferred_pickup_window_end')
        now_local = timezone.localtime(timezone.now())
        pick_date_local = timezone.localtime(pick_date)

        if pick_date_local.date() < now_local.date():
            raise serializers.ValidationError({'preferred_pickup_date': "Pickup date can't be in the past. Please choose today or a future date."})
        if pick_date_local.date() > (now_local + timedelta(days=29)).date():
            raise serializers.ValidationError({'preferred_pickup_date': "Pickup date must be within the next 30 days."})
        if pick_date_local.date() == now_local.date() and win_start and win_start < now_local.time():
            raise serializers.ValidationError({'preferred_pickup_window_start': "Pickup window can't start before the current time for same-day pickups."})
        if win_start and win_end and win_start >= win_end:
            raise serializers.ValidationError({'preferred_pickup_window_start': "End time must be after the start time."})

        # 4. Donor Validation
        donor_id = data.get('donor_user_id')
        if not donor_id:
            if request and request.user.role == UserRole.DONOR:
                donor_id = request.user.user_id
                data['donor_user_id'] = donor_id
            else:
                raise serializers.ValidationError({'donor_user_id': "Please provide a valid donor account."})
        donor = User.objects.filter(pk=donor_id).first()
        if not donor or donor.role != UserRole.DONOR or donor.status != UserAccountStatus.ACTIVE:
            raise serializers.ValidationError({'donor_user_id': "This donor account doesn't exist or is no longer active."})
        if request and request.user.role == UserRole.DONOR and donor_id != request.user.user_id:
            raise serializers.ValidationError({'donor_user_id': "You can only create donations under your own account."})

        # 5. Items Validation
        try:
            raw_items = json.loads(data['items'])
        except (json.JSONDecodeError, TypeError):
            raise serializers.ValidationError({'items': "Invalid items format."})
        if not isinstance(raw_items, list) or not raw_items:
            raise serializers.ValidationError({'items': "At least one item is required."})
        item_serializer = DonationItemUpdateSerializer(data=raw_items, many=True)
        item_serializer.is_valid(raise_exception=True)
        data['items'] = item_serializer.validated_data

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
            'auto_archive_at': validated_data['preferred_pickup_date'] + timedelta(days=30),
            'pickup_barangay': validated_data.pop('_loc_barangay', 'Unknown'),
            'pickup_city': validated_data.pop('_loc_city', 'Unknown'),
        })

        # 3. Leverage ModelSerializer to handle the rest
        return super().create(validated_data)


# ------------------------------------------------------------------------------
# ## Quotation Request Serializer
# ------------------------------------------------------------------------------
class QuotationRequestSerializer(serializers.ModelSerializer):
    dropoff_address = serializers.CharField(source='dropoff_display_address')
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

        if donation:
            total_weight = sum(item.weight_kg for item in donation.items.filter(is_archived=False))
            if total_weight >= Decimal('20'):
                raise serializers.ValidationError({"items": "Total donation items weight must be less than 20 kg."})

        # 1. Coordinate & Location Check
        request = self.context.get('request')
        if request:
            for field in ['dropoff_lat', 'dropoff_lng']:
                raw_val = request.data.get(field)
                if raw_val and not re.match(r'^-?\d+\.\d{7}$', str(raw_val)):
                    raise serializers.ValidationError({field: "Coordinates must be in decimal format with exactly 7 decimal places (e.g. 14.5995000)."})

        location_info = get_city_and_barangay(lat, lng)
        if not location_info:
            raise serializers.ValidationError({"dropoff_location": "We couldn't find that location. Please make sure the dropoff address is within Metro Manila."})

        # 2. Scheduled Time Validation
        if donation and scheduled_time:
            window_start = donation.preferred_pickup_window_start
            window_end = donation.preferred_pickup_window_end

            if scheduled_time < window_start or scheduled_time > window_end:
                raise serializers.ValidationError({"scheduled_time": "Please choose a time within the Donor's Preferred Time Window."})

        return data



# ------------------------------------------------------------------------------
# ## Update-Only Serializers
# ------------------------------------------------------------------------------
class DonationItemUpdateSerializer(serializers.ModelSerializer):
    """Internal serializer to validate individual item updates."""
    item_id = serializers.IntegerField(required=False)
    brand = serializers.CharField(required=False, write_only=True)
    clothing_type = serializers.CharField(required=False, write_only=True)
    fiber_composition = serializers.JSONField(required=False, write_only=True)

    class Meta:
        model = DonationItem
        fields = ['item_id', 'lookup', 'brand', 'clothing_type', 'weight_kg', 'condition_rating', 'is_archived', 'fiber_composition']
        extra_kwargs = {
            'lookup': {'required': False},
            'weight_kg': {'min_value': Decimal('0.01'), 'required': False},
            'condition_rating': {'required': False},
            'is_archived': {'default': False},
        }

    def validate(self, data):
        item_id = data.get('item_id')
        is_archived = data.get('is_archived', False)
        has_brand_type = data.get('brand') and data.get('clothing_type')
        fiber_composition = data.get('fiber_composition')
        has_lookup = bool(data.get('lookup'))

        if has_lookup and (data.get('brand') or data.get('clothing_type') or fiber_composition):
            raise serializers.ValidationError(
                "A lookup already encodes brand, clothing type, and fiber composition. "
                "Do not combine lookup with brand, clothing type, or fiber composition."
            )

        if fiber_composition is not None:
            if not isinstance(fiber_composition, dict) or not fiber_composition:
                raise serializers.ValidationError("fiber_composition must be a non-empty object.")
            if not has_brand_type:
                raise serializers.ValidationError("brand and clothing_type are required with fiber_composition.")
            total = 0
            for fiber, pct in fiber_composition.items():
                if not isinstance(fiber, str) or not fiber.strip():
                    raise serializers.ValidationError("Fiber names must be non-empty strings.")
                try:
                    val = float(pct)
                except (ValueError, TypeError):
                    raise serializers.ValidationError(f"Invalid percentage for '{fiber}'.")
                if val <= 0 or val > 100:
                    raise serializers.ValidationError(f"Percentage for '{fiber}' must be between 0 and 100.")
                total += val
            if abs(total - 100) > 0.011:
                raise serializers.ValidationError(f"Fiber percentages must sum to 100% (got {total:.2f}%).")

        if is_archived:
            if not item_id:
                raise serializers.ValidationError("item_id is required to archive an item.")
            other = [f for f in data if f not in ('item_id', 'is_archived') and data[f]]
            if other:
                raise serializers.ValidationError("Archiving an item cannot be combined with other updates.")
            return data

        if not item_id:
            if (not has_lookup and not has_brand_type) or not data.get('weight_kg') or not data.get('condition_rating'):
                raise serializers.ValidationError("New items need a brand/clothing type or lookup, weight, and condition rating.")
            return data

        update_fields = {'lookup', 'brand', 'clothing_type', 'weight_kg', 'condition_rating', 'fiber_composition'}
        if not any(f in data for f in update_fields):
            raise serializers.ValidationError(f"Please provide at least one field to update for item {item_id}.")

        return data



class DonorDonationUpdateSerializer(serializers.ModelSerializer):
    """Specific serializer for Donors to update their PENDING donations."""
    items = serializers.CharField(required=False)
    donation_image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Donation
        fields = [
            'pickup_display_address', 'pickup_latitude', 'pickup_longitude',
            'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end',
            'items', 'donation_image'
        ]
        extra_kwargs = {}

    def update(self, instance, validated_data):
        validated_data.pop('items', None)
        validated_data.pop('donation_image', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    def validate(self, data):
        # 1. Image Validation
        image = data.get('donation_image')
        if image:
            valid_exts = ['.jpg', '.jpeg', '.png']
            if image.size > 5 * 1024 * 1024 or os.path.splitext(image.name)[1].lower() not in valid_exts:
                raise serializers.ValidationError({'donation_image': "Please upload a JPG or PNG image under 5 MB."})

        # 2. Location Validation
        if 'pickup_latitude' in self.initial_data or 'pickup_longitude' in self.initial_data:
            raw_lat = str(self.initial_data.get('pickup_latitude') or '').strip()
            raw_lng = str(self.initial_data.get('pickup_longitude') or '').strip()
            if not raw_lat or not raw_lng:
                raise serializers.ValidationError({'pickup_location': "Both latitude and longitude are required."})
            if 'pickup_display_address' not in data or not (data.get('pickup_display_address') or '').strip():
                raise serializers.ValidationError({'pickup_display_address': "Please provide a street address when updating coordinates."})
            try:
                loc = get_city_and_barangay(Decimal(raw_lat), Decimal(raw_lng))
                if not loc:
                    raise ValueError
                data['pickup_latitude'] = Decimal(raw_lat)
                data['pickup_longitude'] = Decimal(raw_lng)
                data['pickup_barangay'] = loc['barangay']
                data['pickup_city'] = loc['city']
            except Exception:
                raise serializers.ValidationError({'pickup_location': "We couldn't find that location. Please make sure the pickup address is within Metro Manila."})

        # 3. Date & Time Business Rules
        now_local = timezone.localtime(timezone.now())
        pick_date = data.get('preferred_pickup_date') if 'preferred_pickup_date' in data else self.instance.preferred_pickup_date
        win_start = data.get('preferred_pickup_window_start') if 'preferred_pickup_window_start' in data else self.instance.preferred_pickup_window_start
        win_end = data.get('preferred_pickup_window_end') if 'preferred_pickup_window_end' in data else self.instance.preferred_pickup_window_end
        is_updating_schedule = ('preferred_pickup_date' in data or 'preferred_pickup_window_start' in data or 'preferred_pickup_window_end' in data)

        pick_date_local = timezone.localtime(pick_date)
        if is_updating_schedule and pick_date_local.date() < now_local.date():
            raise serializers.ValidationError({'preferred_pickup_date': "Pickup date can't be in the past. Please choose today or a future date."})
        if 'preferred_pickup_date' in data and pick_date_local.date() > (now_local + timedelta(days=29)).date():
            raise serializers.ValidationError({'preferred_pickup_date': "Pickup date must be within the next 30 days."})
        if is_updating_schedule and pick_date_local.date() == now_local.date() and win_start and win_start < now_local.time():
            raise serializers.ValidationError({'preferred_pickup_window_start': "Pickup window can't start before the current time for same-day pickups."})
        if win_start and win_end and win_start >= win_end:
            raise serializers.ValidationError({'preferred_pickup_window_start': "End time must be after the start time."})

        if 'preferred_pickup_date' in data:
            data['auto_archive_at'] = pick_date + timedelta(days=30)

        # 4. Cross-check: auto_archive_at must be after preferred_pickup_date
        if is_updating_schedule or 'auto_archive_at' in data:
            archive = data.get('auto_archive_at') if 'auto_archive_at' in data else self.instance.auto_archive_at
            if archive and pick_date and timezone.localtime(archive).date() <= timezone.localtime(pick_date).date():
                raise serializers.ValidationError({'auto_archive_at': "Archive date must be after the scheduled pickup date."})

        # 5. Items Validation
        items_json = data.get('items')
        if items_json:
            try:
                raw_items = json.loads(items_json)
                item_serializer = DonationItemUpdateSerializer(data=raw_items, many=True)
                item_serializer.is_valid(raise_exception=True)
                items = item_serializer.validated_data

                existing_item_ids = set(self.instance.items.values_list('item_id', flat=True))
                for i in items:
                    if i.get('item_id') and i['item_id'] not in existing_item_ids:
                        raise ValueError

                active_items_count = self.instance.items.filter(is_archived=False).count()
                num_archiving = len([i for i in items if i.get('is_archived') and i.get('item_id')])
                num_adding = len([i for i in items if not i.get('item_id') and not i.get('is_archived')])
                if (active_items_count - num_archiving + num_adding) < 1:
                    raise ValueError

                data['items'] = items
            except Exception:
                raise serializers.ValidationError({'items': "Each item needs a brand/clothing type or lookup, a weight greater than 0 kg, and a condition rating."})

        return data


class DonationResolveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[DonationStatus.RECEIVED, DonationStatus.REJECTED])
    rejection_reason = serializers.CharField(required=False, allow_blank=True)
    items = serializers.CharField(required=False)

    def validate(self, data):
        status = data.get('status')
        rejection_reason = data.get('rejection_reason')
        items_json = data.get('items')

        if status == DonationStatus.REJECTED and (not rejection_reason or not rejection_reason.strip()):
            raise serializers.ValidationError({'rejection_reason': "Rejection reason is required when status is REJECTED."})

        if items_json:
            try:
                raw_items = json.loads(items_json)
                item_serializer = DonationItemUpdateSerializer(data=raw_items, many=True)
                item_serializer.is_valid(raise_exception=True)
                items = item_serializer.validated_data

                donation = self.context.get('donation')
                if donation:
                    existing_item_ids = set(donation.items.values_list('item_id', flat=True))
                    for i in items:
                        if i.get('item_id') and i['item_id'] not in existing_item_ids:
                            raise ValueError

                    active_items_count = donation.items.filter(is_archived=False).count()
                    num_archiving = len([i for i in items if i.get('is_archived') and i.get('item_id')])
                    num_adding = len([i for i in items if not i.get('item_id') and not i.get('is_archived')])
                    if (active_items_count - num_archiving + num_adding) < 1:
                        raise ValueError

                data['items'] = items
            except Exception:
                raise serializers.ValidationError({'items': "Each item must have a recognized fiber type, a positive weight, and a condition rating."})

        return data


class AdminDonationUpdateSerializer(serializers.ModelSerializer):
    """Specific serializer for Admins to update donations and nested donation items."""
    items = serializers.CharField(required=False)
    donation_image = serializers.ImageField(required=False, allow_null=True)

    # Optional fields for dropoff location (associated Order fields, not on Donation model)
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
        extra_kwargs = {}

    def validate(self, data):
        if not self.instance:
            return data

        current_delivery_method = self.instance.delivery_method
        current_status = self.instance.status

        # 1. Image Validation
        image = data.get('donation_image')
        if image:
            valid_exts = ['.jpg', '.jpeg', '.png']
            if image.size > 5 * 1024 * 1024 or os.path.splitext(image.name)[1].lower() not in valid_exts:
                raise serializers.ValidationError({'donation_image': "Please upload a JPG or PNG image under 5 MB."})

        if 'auto_archive_at' in data and data['auto_archive_at'] and data['auto_archive_at'] < timezone.now():
            raise serializers.ValidationError({'auto_archive_at': "Archive date must be in the future."})

        # 2. State-based Lock Validation
        if current_delivery_method == DonationDeliveryMethod.DELIVERY:
            if current_status == DonationStatus.CLAIMED:
                locked = set(data.keys()).intersection({
                    'pickup_display_address', 'pickup_latitude', 'pickup_longitude',
                    'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end'
                })
                if locked:
                    raise serializers.ValidationError("Pickup details can't be edited once a delivery has been claimed.")
            elif current_status in [DonationStatus.IN_TRANSIT, DonationStatus.RECEIVED, DonationStatus.REJECTED]:
                locked = set(data.keys()).intersection({
                    'dropoff_display_address', 'dropoff_latitude', 'dropoff_longitude',
                    'pickup_display_address', 'pickup_latitude', 'pickup_longitude',
                    'preferred_pickup_date', 'preferred_pickup_window_start', 'preferred_pickup_window_end'
                })
                if locked:
                    raise serializers.ValidationError("Delivery pickup and dropoff details can't be edited once a delivery is in transit or completed.")

        # 3. Coordinate & Location Validation
        if 'pickup_latitude' in self.initial_data or 'pickup_longitude' in self.initial_data:
            raw_lat = str(self.initial_data.get('pickup_latitude') or '').strip()
            raw_lng = str(self.initial_data.get('pickup_longitude') or '').strip()
            if not raw_lat or not raw_lng:
                raise serializers.ValidationError({'pickup_location': "Both latitude and longitude are required."})
            if 'pickup_display_address' not in data or not (data.get('pickup_display_address') or '').strip():
                raise serializers.ValidationError({'pickup_display_address': "Please provide a street address when updating coordinates."})
            try:
                loc = get_city_and_barangay(Decimal(raw_lat), Decimal(raw_lng))
                if not loc:
                    raise ValueError
                data['pickup_latitude'] = Decimal(raw_lat)
                data['pickup_longitude'] = Decimal(raw_lng)
                data['pickup_barangay'] = loc['barangay']
                data['pickup_city'] = loc['city']
            except Exception:
                raise serializers.ValidationError({'pickup_location': "We couldn't find that location. Please make sure the pickup address is within Metro Manila."})

        # 4. Dropoff Coordinate & Location Validation
        if current_delivery_method == DonationDeliveryMethod.PICKUP:
            for field in ['dropoff_display_address', 'dropoff_latitude', 'dropoff_longitude']:
                if field in data:
                    raise serializers.ValidationError({field: "Dropoff details aren't applicable for self-pickup donations."})
        elif 'dropoff_latitude' in self.initial_data or 'dropoff_longitude' in self.initial_data:
            raw_lat = str(self.initial_data.get('dropoff_latitude') or '').strip()
            raw_lng = str(self.initial_data.get('dropoff_longitude') or '').strip()
            if not raw_lat or not raw_lng:
                raise serializers.ValidationError({'dropoff_location': "Both latitude and longitude are required."})
            if 'dropoff_display_address' not in data or not (data.get('dropoff_display_address') or '').strip():
                raise serializers.ValidationError({'dropoff_display_address': "Please provide a street address when updating coordinates."})
            try:
                loc = get_city_and_barangay(Decimal(raw_lat), Decimal(raw_lng))
                if not loc:
                    raise ValueError
            except Exception:
                raise serializers.ValidationError({'dropoff_location': "We couldn't find that location. Please make sure the dropoff address is within Metro Manila."})

        # 5. Date & Time Business Rules
        now_local = timezone.localtime(timezone.now())
        pick_date = data.get('preferred_pickup_date') if 'preferred_pickup_date' in data else self.instance.preferred_pickup_date
        win_start = data.get('preferred_pickup_window_start') if 'preferred_pickup_window_start' in data else self.instance.preferred_pickup_window_start
        win_end = data.get('preferred_pickup_window_end') if 'preferred_pickup_window_end' in data else self.instance.preferred_pickup_window_end
        is_updating_schedule = ('preferred_pickup_date' in data or 'preferred_pickup_window_start' in data or 'preferred_pickup_window_end' in data)

        pick_date_local = timezone.localtime(pick_date)
        if is_updating_schedule and pick_date_local.date() < now_local.date():
            raise serializers.ValidationError({'preferred_pickup_date': "Pickup date can't be in the past. Please choose today or a future date."})
        if 'preferred_pickup_date' in data and pick_date_local.date() > (now_local + timedelta(days=29)).date():
            raise serializers.ValidationError({'preferred_pickup_date': "Pickup date must be within the next 30 days."})
        if is_updating_schedule and pick_date_local.date() == now_local.date() and win_start and win_start < now_local.time():
            raise serializers.ValidationError({'preferred_pickup_window_start': "Pickup window can't start before the current time for same-day pickups."})
        if win_start and win_end and win_start >= win_end:
            raise serializers.ValidationError({'preferred_pickup_window_start': "End time must be after the start time."})

        # 6. Cross-check: auto_archive_at must be after preferred_pickup_date
        if is_updating_schedule or 'auto_archive_at' in data:
            archive = data.get('auto_archive_at') if 'auto_archive_at' in data else self.instance.auto_archive_at
            if archive and pick_date and timezone.localtime(archive).date() <= timezone.localtime(pick_date).date():
                raise serializers.ValidationError({'auto_archive_at': "Archive date must be after the scheduled pickup date."})

        # 7. Items Validation
        items_json = data.get('items')
        if items_json:
            if current_status == DonationStatus.RECEIVED:
                raise serializers.ValidationError({'items': "Items can't be edited after the donation has been received into inventory."})
            try:
                raw_items = json.loads(items_json)
                item_serializer = DonationItemUpdateSerializer(data=raw_items, many=True)
                item_serializer.is_valid(raise_exception=True)
                items = item_serializer.validated_data

                existing_item_ids = set(self.instance.items.values_list('item_id', flat=True))
                for i in items:
                    if i.get('item_id') and i['item_id'] not in existing_item_ids:
                        raise ValueError

                active_items_count = self.instance.items.filter(is_archived=False).count()
                num_archiving = len([i for i in items if i.get('is_archived') and i.get('item_id')])
                num_adding = len([i for i in items if not i.get('item_id') and not i.get('is_archived')])
                if (active_items_count - num_archiving + num_adding) < 1:
                    raise ValueError

                data['items'] = items
            except Exception:
                raise serializers.ValidationError({'items': "Each item needs a brand/clothing type or lookup, a weight greater than 0 kg, and a condition rating."})

        return data
