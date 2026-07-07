import os

from django.core.wsgi import get_wsgi_application
from a2wsgi import ASGIMiddleware

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'WeaveForward_Backend.settings')

django_app = get_wsgi_application()

from fiber_match_api.fastapi_app import app as fastapi_app

fastapi_wsgi = ASGIMiddleware(fastapi_app)


def application(environ, start_response):
    if (
        environ.get("REQUEST_METHOD") == "POST"
        and environ.get("PATH_INFO", "") in ("/api/match-predict", "/api/match-predict/")
    ):
        return fastapi_wsgi(environ, start_response)
    return django_app(environ, start_response)
