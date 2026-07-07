from django import forms
from django.contrib import admin

from .models import User, Upload, BrandFiberLookup, Donation, DonationItem, MatchPrediction, InventoryLedger, Subscription, SubscriptionPayment, AuditTrail, ApiToken, Order, OrderPayment


class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = "__all__"
        widgets = {
            "password": forms.PasswordInput(render_value=True),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = False
        self.fields["last_name"].required = False
        self.fields["middle_name"].required = False
        self.fields["business_name"].required = False

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password and (self.instance._state.adding or password != self.instance.password):
            user.set_password(password)
        if commit:
            user.save()
            self.save_m2m()
        return user


class UserAdmin(admin.ModelAdmin):
    form = UserAdminForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "middle_name", "business_name", "contact_no")}),
        ("Permissions", {"fields": ("role", "status")}),
    )
    list_display = ("email", "first_name", "last_name", "role", "status")
    list_filter = ("role", "status")
    search_fields = ("email", "first_name", "last_name", "business_name")
    ordering = ("email",)


admin.site.register(User, UserAdmin)
admin.site.register(Upload)
admin.site.register(BrandFiberLookup)
admin.site.register(Donation)
admin.site.register(DonationItem)
admin.site.register(MatchPrediction)
admin.site.register(InventoryLedger)
admin.site.register(Subscription)
admin.site.register(SubscriptionPayment)
admin.site.register(AuditTrail)
admin.site.register(ApiToken)
admin.site.register(Order)
admin.site.register(OrderPayment)

admin.site.site_header = "WeaveForward · Super Admin"
admin.site.site_title = "WeaveForward Admin"
admin.site.index_title = "Dashboard"

