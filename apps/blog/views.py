from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, permissions

import apps.blog.serializers as serializers
from apps.blog.models import BlogPost
from apps.shared.addons.validations import success_response


class BlogPostListView(generics.ListAPIView):
    queryset = BlogPost.objects.filter(is_published=True)
    serializer_class = serializers.BlogPostListSerializer
    permission_classes = [permissions.AllowAny]
    # Anonymous and search-backed, so it needs a bound: ScopedRateThrottle is
    # the only global throttle class and it is inert without a scope.
    throttle_scope = "public_read"
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ["title", "excerpt", "tags"]
    ordering_fields = ["published_at", "created_time"]
    ordering = ["-published_at"]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)


class BlogPostDetailView(generics.RetrieveAPIView):
    queryset = BlogPost.objects.filter(is_published=True)
    serializer_class = serializers.BlogPostDetailSerializer
    permission_classes = [permissions.AllowAny]
    throttle_scope = "public_read"
    lookup_field = "slug"

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data)
