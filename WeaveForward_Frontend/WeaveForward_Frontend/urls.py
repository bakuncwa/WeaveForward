import os

from django.conf import settings
from django.urls import path, include, re_path
from django.views.static import serve

urlpatterns = [
    path('', include('frontend.urls')),
]

# Cloud Run serves collected static files after `collectstatic`.
# This local fallback serves source static assets directly when running outside Cloud Run.
if not os.getenv('K_SERVICE') and settings.STATICFILES_DIRS:
    urlpatterns.append(
        re_path(
            r'^static/(?P<path>.*)$',
            serve,
            {'document_root': str(settings.STATICFILES_DIRS[0])},
        )
    )
