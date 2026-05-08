from rest_framework.response import Response

class PaginatedResponseMixin:
    """Mixin to provide a helper for returning paginated responses in custom list/action methods."""
    
    def get_paginated_response_data(self, queryset, serializer_class=None):
        """
        Paginates a queryset and returns a Response object.
        If pagination is not configured or not applicable, returns a standard Response.
        """
        page = self.paginate_queryset(queryset)
        serializer_class = serializer_class or self.get_serializer_class()
        
        if page is not None:
            serializer = serializer_class(page, many=True, context=self.get_serializer_context())
            return self.get_paginated_response(serializer.data)

        serializer = serializer_class(queryset, many=True, context=self.get_serializer_context())
        return Response(serializer.data)
