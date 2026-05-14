from rest_framework.response import Response

class PaginatedResponseMixin:
    """Mixin to provide a helper for returning paginated responses in custom list/action methods."""
    
    def get_paginated_response_data(self, queryset, serializer_class=None):
        """
        Paginates a queryset and returns a Response object.
        If 'nopaginate=true' is in query params, returns the full standard Response.
        """
        # Support disabling pagination via query param
        if hasattr(self, 'request') and self.request.query_params.get('nopaginate') == 'true':
            serializer_class = serializer_class or self.get_serializer_class()
            serializer = serializer_class(queryset, many=True, context=self.get_serializer_context())
            return Response(serializer.data)

        page = self.paginate_queryset(queryset)
        serializer_class = serializer_class or self.get_serializer_class()
        
        if page is not None:
            serializer = serializer_class(page, many=True, context=self.get_serializer_context())
            return self.get_paginated_response(serializer.data)

        serializer = serializer_class(queryset, many=True, context=self.get_serializer_context())
        return Response(serializer.data)
