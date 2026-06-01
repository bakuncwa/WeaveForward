from .constants import TEXT_FIELD_MAX_LENGTH


def frontend_constants(request):
    return {
        "TEXT_FIELD_MAX_LENGTH": TEXT_FIELD_MAX_LENGTH,
    }
