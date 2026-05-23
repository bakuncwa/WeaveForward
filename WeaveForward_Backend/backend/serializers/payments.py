from rest_framework import serializers
from backend.models import SubscriptionPayment, OrderPayment

class SubscriptionPaymentSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    reference = serializers.CharField(source='payment_reference', allow_null=True)
    tuab = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPayment
        fields = ['type', 'amount', 'reference', 'status', 'created_at', 'tuab']

    def get_type(self, obj):
        return 'Subscription Payment'

    def get_status(self, obj):
        val = str(obj.status)
        return val.title() if val else ''
        
    def get_tuab(self, obj):
        if obj.subscription and obj.subscription.user:
            user = obj.subscription.user
            return user.business_name or f"{user.first_name or ''} {user.last_name or ''}".strip()
        return ''


class OrderPaymentSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    reference = serializers.CharField(source='payment_reference', allow_null=True)
    tuab = serializers.SerializerMethodField()

    class Meta:
        model = OrderPayment
        fields = ['type', 'amount', 'reference', 'status', 'created_at', 'tuab']

    def get_type(self, obj):
        return 'Order Payment'

    def get_status(self, obj):
        val = str(obj.status)
        return val.title() if val else ''
        
    def get_tuab(self, obj):
        if obj.order and obj.order.donation and obj.order.donation.claimed_by_tuab:
            user = obj.order.donation.claimed_by_tuab
            return user.business_name or f"{user.first_name or ''} {user.last_name or ''}".strip()
        return ''
