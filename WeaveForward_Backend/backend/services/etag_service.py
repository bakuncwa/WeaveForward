from datetime import timezone as dt_timezone


def build_etag_from_datetime(value):
    if value.tzinfo is None:
        normalized = value.replace(tzinfo=dt_timezone.utc)
    else:
        normalized = value.astimezone(dt_timezone.utc)
    return f'W/"{normalized.isoformat(timespec="microseconds")}"'


def build_updated_at_etag(instance):
    return build_etag_from_datetime(instance.updated_at)


def normalize_etag(etag):
    if etag is None:
        return None
    etag = etag.strip()
    if etag.startswith('W/'):
        return etag[2:]
    return etag


def matches_if_match(current_etag, if_match_header):
    return normalize_etag(if_match_header) == normalize_etag(current_etag)
