from django.core.files.storage import default_storage


def build_upload_url(upload, context=None):
    if not upload or not upload.file_path:
        return None

    url = default_storage.url(upload.file_path)
    if url.startswith(('http://', 'https://')):
        return url

    request = context.get('request') if context else None
    return request.build_absolute_uri(url) if request else url
