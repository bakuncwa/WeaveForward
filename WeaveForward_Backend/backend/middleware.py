from django.http import JsonResponse

from .constants import TEXT_FIELD_MAX_LENGTH


class QueryStringLengthLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if len(request.META.get("QUERY_STRING", "")) > TEXT_FIELD_MAX_LENGTH:
            return JsonResponse(
                {"detail": f"Query string must be no more than {TEXT_FIELD_MAX_LENGTH} characters."},
                status=400,
            )

        return self.get_response(request)
