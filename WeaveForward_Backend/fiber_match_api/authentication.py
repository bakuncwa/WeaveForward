import hashlib, hmac
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from backend.models import ApiToken


class ApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None

        parts = auth_header.split(" ")
        if len(parts) != 2 or parts[0] != "ApiKey":
            return None

        api_key = parts[1]
        hashed_key = hmac.new(settings.SECRET_KEY.encode(), api_key.encode(), hashlib.sha256).hexdigest()[:50]
        try:
            api_token = ApiToken.objects.select_related("user").get(token=hashed_key)
            return (api_token.user, api_token)
        except ApiToken.DoesNotExist:
            raise AuthenticationFailed("Invalid API key.")
