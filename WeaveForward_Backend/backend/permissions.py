from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated

from .models import Subscription, SubscriptionStatus, UserAccountStatus, UserRole


class IsRole(BasePermission):
    allowed_roles = ()
    message = "You do not have permission to access this resource."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role in self.allowed_roles)


class IsActiveRole(IsRole):
    def has_permission(self, request, view):
        return (
            super().has_permission(request, view)
            and request.user.status == UserAccountStatus.ACTIVE
        )


class IsActiveAdmin(IsActiveRole):
    allowed_roles = (UserRole.ADMIN,)
    message = "Active admin account required."


class IsActiveDonor(IsActiveRole):
    allowed_roles = (UserRole.DONOR,)
    message = "Active donor account required."


class IsActiveTUAB(IsActiveRole):
    allowed_roles = (UserRole.TUAB,)
    message = "Active TUAB account required."


class IsActiveAdminOrDonor(IsActiveRole):
    allowed_roles = (UserRole.ADMIN, UserRole.DONOR)
    message = "Only active admins and donors can access this resource."


class IsActiveAdminOrTUAB(IsActiveRole):
    allowed_roles = (UserRole.ADMIN, UserRole.TUAB)
    message = "You do not have permission to view this resource."


class IsActiveTUABWithActiveSubscription(IsActiveTUAB):
    message = "No active subscription found. Please upgrade to access Donation Recommendations."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        try:
            subscription = Subscription.objects.filter(
                user=request.user,
                status=SubscriptionStatus.ACTIVE,
            ).first()
            if not subscription or (subscription.end_date and subscription.end_date < timezone.now()):
                raise PermissionDenied("No active subscription found. Please upgrade to access Donation Recommendations.")
        except Exception as exc:
            if isinstance(exc, PermissionDenied):
                raise
            raise PermissionDenied("Unable to verify subscription status.")
        return True


class IsActiveAdminOrTUABWithActiveSubscription(IsActiveAdminOrTUAB):
    message = "Only active admins or active TUABs with an active subscription can access this resource."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False

        if request.user.role == UserRole.ADMIN:
            return True

        if not Subscription.objects.filter(
            user=request.user,
            status=SubscriptionStatus.ACTIVE,
        ).exists():
            raise PermissionDenied("Active subscription required.")
        return True
