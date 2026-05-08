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
    # Ensure fields_modified does not exceed the 100-char limit in models.py
    if fields_modified and len(fields_modified) > 100:
        fields_modified = fields_modified[:97] + "..."

    return AuditTrail.objects.create(
        actor=actor,
        entity_type=entity_type,
        action=action,
        ip_address=ip_address,
        fields_modified=fields_modified
    )
