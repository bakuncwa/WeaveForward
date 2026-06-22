from .api_service import api_call


def format_errors(errors):
    """Convert snake_case error keys to Title Case for display (e.g. business_name -> Business Name)."""
    result = {}
    for k, v in errors.items():
        if not isinstance(v, list):
            v = [v]
        if k == 'non_field_errors':
            result['Error'] = v
        else:
            result[k.replace('_', ' ').title()] = v
    return result

async def get_paginated_data(request, endpoint, params=None, page_size=10):
    """Fetch and parse paginated data from the API, including search support."""
    page = request.GET.get('page', 1)
    search_query = request.GET.get('q', '')
    
    api_params = params.copy() if params else {}
    api_params.update({'page': page, 'search': search_query})
    
    response = await api_call(request, 'GET', endpoint, params=api_params)
    data = response.json() if response.status_code == 200 else {'results': [], 'count': 0, 'next': None, 'previous': None}
    
    if isinstance(data, list):
        return {
            'results': data,
            'count': len(data),
            'total_pages': 1,
            'current_page': 1,
            'has_next': False,
            'has_prev': False,
            'search_query': search_query
        }
    
    count = data.get('count', 0)
    ret = {
        'results': data.get('results', []),
        'count': count,
        'total_pages': (count + page_size - 1) // page_size,
        'current_page': int(page),
        'has_next': data.get('next') is not None,
        'has_prev': data.get('previous') is not None,
        'search_query': search_query
    }
    
    # Forward any extra keys (like category_summary) that the backend might have added
    for key, value in data.items():
        if key not in ['results', 'count', 'next', 'previous']:
            ret[key] = value
            
    return ret
