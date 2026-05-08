import json

from ..models import AuditTrail

def get_client_ip(request):
    """
    Extract the real user IP from the X-Forwarded-For header (Cloud Run ready).
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def log_audit(actor, entity_type, action, ip_address=None, fields_modified=None):
    """
    Utility to create an AuditTrail record.
    """
    if fields_modified is not None:
        if isinstance(fields_modified, str):
            serialized_fields_modified = fields_modified
        else:
            serialized_fields_modified = json.dumps(fields_modified, separators=(',', ':'))

        max_length = AuditTrail._meta.get_field('fields_modified').max_length
        if max_length and len(serialized_fields_modified) > max_length:
            serialized_fields_modified = serialized_fields_modified[:max_length - 3] + "..."
        fields_modified = serialized_fields_modified

    return AuditTrail.objects.create(
        actor=actor,
        entity_type=entity_type,
        action=action,
        ip_address=ip_address,
        fields_modified=fields_modified
    )
