def format_errors(errors):
    """Convert snake_case error keys to Title Case for display (e.g. business_name → Business Name)."""
    return {k.replace('_', ' ').title(): v for k, v in errors.items()}
