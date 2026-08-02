"""Instagram comment automation: trigger words and comment responses."""

from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions

from apps.integration.models import (
    CommentTriggerWord,
    InstagramCommentResponse,
)
from apps.integration.serializers import (
    CommentTriggerWordSerializer,
    InstagramCommentResponseSerializer,
)
from apps.integration.views.mixins import (
    IntegrationOwnedQuerysetMixin,
    owned_integrations,
)
from apps.shared.addons.enums import IntegrationTypes
from apps.shared.addons.validations import error_response, success_response


class CommentTriggerWordListCreateView(generics.CreateAPIView):
    queryset = CommentTriggerWord.objects.all()
    serializer_class = CommentTriggerWordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Trigger word muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class CommentTriggerWordRetrieveView(IntegrationOwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    owner_path = "instagram_comment_responses__integration"
    queryset = CommentTriggerWord.objects.all()
    serializer_class = CommentTriggerWordSerializer
    permission_classes = [permissions.IsAuthenticated]


    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Trigger word muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Trigger word muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Trigger word muvaffaqiyatli o'chirildi"), code=204)


class InstagramCommentResponseListCreateView(generics.ListCreateAPIView):
    queryset = InstagramCommentResponse.objects.all()
    serializer_class = InstagramCommentResponseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _integration(self):
        """The Instagram integration named by the URL, if the caller owns it.

        Both halves of this view keyed off the URL id alone: GET listed another
        tenant's comment automation, and POST attached a new auto-reply to
        their account — i.e. made *their* verified Instagram profile DM its
        commenters with attacker-chosen text.
        """
        return owned_integrations(self.request.user).filter(
            id=self.kwargs.get('integration_id'),
            integration_type=IntegrationTypes.INSTAGRAM.value,
        ).first()

    def get_queryset(self):
        integration = self._integration()
        if integration is None:
            return self.queryset.none()
        return self.queryset.filter(integration=integration)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return success_response(message=_("Comment responses muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def create(self, request, *args, **kwargs):
        integration = self._integration()
        if integration is None:
            return error_response(message=_("Integration topilmadi"), code=404)

        serializer = self.get_serializer(data=request.data, context={"integration": integration})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Comment response muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class InstagramCommentResponseRetrieveView(IntegrationOwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    owner_path = "integration"
    queryset = InstagramCommentResponse.objects.all()
    serializer_class = InstagramCommentResponseSerializer
    permission_classes = [permissions.IsAuthenticated]


    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Comment response muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Comment response muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Comment response muvaffaqiyatli o'chirildi"), code=204)
