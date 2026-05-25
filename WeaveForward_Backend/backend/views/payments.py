from rest_framework import views, permissions, status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from backend.models import UserRole, UserAccountStatus, SubscriptionPayment, OrderPayment
from backend.serializers.payments import SubscriptionPaymentSerializer, OrderPaymentSerializer

class PaymentPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class PaymentListView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PaymentPagination

    def get(self, request):
        user = request.user
        
        # Complexity notes:
        # - Let m = number of subscription payments.
        # - Let n = number of order payments.
        # - Fetching and merging the two payment lists is O(m + n).
        # - Sorting the combined list by created_at is O((m + n) log(m + n)).
        # - Overall: O((m + n) log(m + n)).
        if user.status != UserAccountStatus.ACTIVE or user.role not in [UserRole.ADMIN, UserRole.TUAB]:
            return Response({'detail': 'You do not have permission to view this resource.'}, status=status.HTTP_403_FORBIDDEN)
            
        if user.role == UserRole.ADMIN:
            subs_qs = SubscriptionPayment.objects.all().order_by('-created_at')
            orders_qs = OrderPayment.objects.all().order_by('-created_at')
        else:
            subs_qs = SubscriptionPayment.objects.filter(subscription__user=user).order_by('-created_at')
            orders_qs = OrderPayment.objects.filter(order__donation__claimed_by_tuab=user).order_by('-created_at')
            
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
                
        paginator = PaymentPagination()
        paginated_payments = paginator.paginate_queryset(payments, request, view=self)
        return paginator.get_paginated_response(paginated_payments)

class PaymentMeView(PaymentListView):
    def get(self, request):
        if request.user.role != UserRole.TUAB:
            return Response({'detail': 'You do not have permission to view this resource.'}, status=status.HTTP_403_FORBIDDEN)
        return super().get(request)
