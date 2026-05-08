from django.core.files.storage import default_storage
from rest_framework import serializers

from ..models import Upload, User


class UploadSerializer(serializers.ModelSerializer):
    """Full metadata for uploaded files with absolute URLs."""
    file_path = serializers.SerializerMethodField()

    class Meta:
        model = Upload
        fields = ['upload_id', 'file_path', 'name']

    def get_file_path(self, obj):
        if not obj.file_path:
            return None
        url = default_storage.url(obj.file_path)
        if url.startswith(('http://', 'https://')):
            return url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class UserSerializer(serializers.ModelSerializer):
    """Full user profile serializer."""
    upload = UploadSerializer(read_only=True)

    class Meta:
        model = User
        exclude = ['password', 'totp_secret']


class PublicUserSerializer(serializers.ModelSerializer):
    """Limited profile serializer for non-admin views."""
    upload = UploadSerializer(read_only=True)

    class Meta:
        model = User
        exclude = [
            'password', 'totp_secret', 'maya_customer_id', 'maya_card_id',
            'is_2fa_enabled', 'created_at', 'updated_at', 'documentation'
        ]



