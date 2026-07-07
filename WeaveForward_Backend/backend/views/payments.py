from rest_framework import views
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from decimal import Decimal
from backend.models import UserRole, SubscriptionPayment, OrderPayment
from backend.permissions import IsActiveAdminOrTUAB, IsActiveTUAB
from backend.serializers.payments import SubscriptionPaymentSerializer, OrderPaymentSerializer

class PaymentPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class PaymentListView(views.APIView):
    permission_classes = [IsActiveAdminOrTUAB]
    pagination_class = PaymentPagination

    def get(self, request):
        user = request.user
        
        # Complexity notes:
        # - Let m = number of subscription payments.
        # - Let n = number of order payments.
        # - Fetching and merging the two payment lists is O(m + n).
        # - Sorting the combined list by created_at is O((m + n) log(m + n)).
        # - Overall: O((m + n) log(m + n)).
        if user.role == UserRole.ADMIN:
            subs_qs = SubscriptionPayment.objects.select_related(
                'subscription', 'subscription__user'
            ).order_by('-created_at')
            orders_qs = OrderPayment.objects.select_related(
                'order', 'order__donation', 'order__donation__claimed_by_tuab'
            ).order_by('-created_at')
        else:
            subs_qs = SubscriptionPayment.objects.select_related(
                'subscription', 'subscription__user'
            ).filter(subscription__user=user).order_by('-created_at')
            orders_qs = OrderPayment.objects.select_related(
                'order', 'order__donation', 'order__donation__claimed_by_tuab'
            ).filter(order__donation__claimed_by_tuab=user).order_by('-created_at')
            
        subs_data = SubscriptionPaymentSerializer(subs_qs, many=True).data
        orders_data = OrderPaymentSerializer(orders_qs, many=True).data
        
        payments = subs_data + orders_data
        payments.sort(key=lambda x: x['created_at'], reverse=True)
        
        for p in payments:
            if p.get('reference') is None:
                p['reference'] = ''
                
        q = request.query_params.get('search', '').strip().lower()
        ref_q = request.query_params.get('reference', '').strip().lower()
        
        if q or ref_q:
            filtered = []
            for p in payments:
                ref = p['reference'].lower()
                typ = p.get('type', '').lower()
                tuab = p.get('tuab', '').lower() if user.role == UserRole.ADMIN else ''
                
                matches_q = not q or (q in ref or q in typ or (user.role == UserRole.ADMIN and q in tuab))
                matches_ref = not ref_q or (ref_q in ref)
                
                if matches_q and matches_ref:
                    filtered.append(p)
            payments = filtered
                
        ordering = request.query_params.get('ordering')
        if ordering:
            reverse = ordering.startswith('-')
            key = ordering.lstrip('-')
            if key in ('tuab', 'type', 'amount', 'reference', 'status', 'created_at'):
                if key == 'amount':
                    payments.sort(key=lambda p: Decimal(str(p.get('amount') or '0')), reverse=reverse)
                else:
                    payments.sort(key=lambda p, k=key: (p.get(k) or ''), reverse=reverse)

        paginator = PaymentPagination()
        paginated_payments = paginator.paginate_queryset(payments, request, view=self)
        return paginator.get_paginated_response(paginated_payments)

class PaymentMeView(PaymentListView):
    permission_classes = [IsActiveTUAB]

    def get(self, request):
        return super().get(request)
