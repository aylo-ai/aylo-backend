"""Instagram post listing (Graph API passthrough) and stored media CRUD."""

from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions
from rest_framework.views import APIView

from apps.integration.models import Integration, InstagramMedia
from apps.integration.serializers import InstagramMediaSerializer
from apps.integration.views.mixins import (
    IntegrationOwnedQuerysetMixin,
    owned_integrations,
)
from apps.shared import http
from apps.shared.addons.enums import IntegrationTypes
from apps.shared.addons.validations import error_response, success_response


class InstagramPostListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        integration_id = self.kwargs.get('pk')
        # Owner-scoped: this endpoint spends the *integration's* stored access
        # token, so an id-only lookup let any authenticated caller page through
        # another tenant's Instagram media with that tenant's credentials.
        integration = owned_integrations(request.user).filter(
            id=integration_id, integration_type=IntegrationTypes.INSTAGRAM.value,
        ).first()
        if not integration:
            return error_response(message=_("Integration topilmadi"), code=400)
        access_token = integration.api_token
        url = "https://graph.instagram.com/v23.0/me/media"
        params = {
            "access_token": access_token,
            "fields": "id,media_type,media_url,username,timestamp,caption,comments_count,like_count,permalink,thumbnail_url,children{media_type,media_url}",
            "limit": 50
        }
        all_posts = []
        max_pages = 5
        for _page in range(max_pages):
            response = http.get(url, params=params)
            if response.status_code != 200:
                break
            json_data = response.json()
            all_posts.extend(json_data.get("data", []))
            next_url = json_data.get("paging", {}).get("next")
            if not next_url:
                break
            url = next_url
            params = {}
        if all_posts:
            return success_response(message=_("Instagram post muvaffaqiyatli olindi"), code=200, data=all_posts)
        else:
            return error_response(message=_("Instagram post topilmadi"), code=400)


class InstagramMediaRetrieveView(IntegrationOwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    owner_path = "instagram_comment_responses__integration"
    queryset = InstagramMedia.objects.all()
    serializer_class = InstagramMediaSerializer
    permission_classes = [permissions.IsAuthenticated]


    def get_serializer_context(self):
        context = super().get_serializer_context()
        # Add custom things here
        context["integration"] = Integration.objects.filter(
            user=self.request.user,
            integration_type=IntegrationTypes.INSTAGRAM.value
        ).first()
        return context

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Instagram media muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Instagram media muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Instagram media muvaffaqiyatli o'chirildi"), code=204)
