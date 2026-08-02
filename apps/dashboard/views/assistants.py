"""Dashboard assistant, assistant-file and prompt-template endpoints."""
from rest_framework import generics, filters
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from apps.user.models import User
from apps.assistant.models import Assistant, AssistantFileUpload, PromptTemplate
from apps.assistant.serializers import AssistantSerializer, AssistantFileUploadSerializer
from apps.shared.permissions import IsAdmin, IsDashboardUser
from apps.shared.pagination import StandardResultsSetPagination
from apps.dashboard.filters import AssistantFilter
from apps.dashboard.models import AuditLog
from apps.dashboard.serializers.assistants import (
    DashboardAssistantListSerializer,
    DashboardAssistantCreateSerializer,
    DashboardAssistantCreateUserSerializer,
    DashboardAssistantFileUploadSerializer,
    AssistantFileFilterSerializer,
    DashboardPromptTemplateSerializer,
)
from apps.dashboard.views.base import get_client_ip
from apps.dashboard.views.mixins import (
    DashboardCreateMixin,
    DashboardDestroyMixin,
    DashboardListMixin,
    DashboardPartialUpdateMixin,
    DashboardRetrieveMixin,
    DashboardStatsListMixin,
)
from apps.shared.addons.validations import success_response, error_response


class DashboardAssistantList(DashboardStatsListMixin, generics.ListCreateAPIView):
    queryset = Assistant.objects.select_related('user').all()
    serializer_class = DashboardAssistantListSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    filterset_class = AssistantFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "user__username", "user__phone_number", "user__email", "company_name"]
    ordering_fields = ['name', 'created_time', 'company_name', 'is_active', 'language', 'personality_style']
    list_message = "Assistants retrieved successfully"

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return DashboardAssistantCreateSerializer
        return DashboardAssistantListSerializer

    def get_list_stats(self, queryset):
        # Global stats (independent of pagination/filters)
        all_assistants = Assistant.objects.all()
        return {
            'total': all_assistants.count(),
            'active': all_assistants.filter(is_active=True).count(),
            'ai_enabled': all_assistants.filter(ai_enabled=True).count(),
            'with_integrations': all_assistants.filter(
                integrations__isnull=False
            ).distinct().count(),
        }

    def create(self, request, *args, **kwargs):
        user_serializer = DashboardAssistantCreateUserSerializer(data=request.data)
        user_serializer.is_valid(raise_exception=True)
        try:
            target_user = User.objects.get(id=user_serializer.validated_data['user'])
        except User.DoesNotExist:
            return error_response(message="User not found", code=404)

        serializer = DashboardAssistantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assistant = serializer.save(user=target_user, created_by=request.user)

        AuditLog.log(
            user=request.user, action='create', target_type='assistant',
            target_id=assistant.id, target_repr=assistant.name,
            details={'user': str(target_user.id), 'data': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(data=AssistantSerializer(assistant).data, message="Assistant created successfully", code=201)


class DashboardAssistantDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    permission_classes = [IsDashboardUser]

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Assistant.objects.filter(id=pk)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.log(
            user=request.user, action='update', target_type='assistant',
            target_id=instance.id, target_repr=instance.name,
            details={'changes': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(data=serializer.data, message="Assistant updated successfully", code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        AuditLog.log(
            user=request.user, action='delete', target_type='assistant',
            target_id=instance.id, target_repr=instance.name,
            ip_address=get_client_ip(request),
        )
        instance.delete()
        return success_response(message="Assistant deleted successfully", code=200)


class DashboardAssistantToggleActive(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            assistant = Assistant.objects.get(id=pk)
        except Assistant.DoesNotExist:
            return error_response(message="Assistant not found", code=404)

        assistant.is_active = not assistant.is_active
        assistant.save(update_fields=['is_active'])

        AuditLog.log(
            user=request.user,
            action='activate' if assistant.is_active else 'deactivate',
            target_type='assistant',
            target_id=pk, target_repr=assistant.name,
            details={'is_active': assistant.is_active},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'is_active': assistant.is_active},
            message=f"Assistant {'activated' if assistant.is_active else 'deactivated'}",
            code=200
        )


class DashboardAssistantFileUploadList(DashboardListMixin, generics.ListCreateAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = DashboardAssistantFileUploadSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    list_message = "Assistant file uploads retrieved successfully"

    def get_queryset(self):
        queryset = super().get_queryset()
        assistant_id = self.request.query_params.get('assistant')
        if assistant_id:
            # A raw, unvalidated UUID reaching the ORM is a 500, not a 400.
            filter_serializer = AssistantFileFilterSerializer(data={'assistant': assistant_id})
            filter_serializer.is_valid(raise_exception=True)
            queryset = queryset.filter(assistant_id=filter_serializer.validated_data['assistant'])
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        AuditLog.log(
            user=request.user, action='create', target_type='assistant_file',
            target_id=instance.id, target_repr=str(instance),
            details={'assistant': str(request.data.get('assistant'))},
            ip_address=get_client_ip(request),
        )
        return success_response(data=serializer.data, message="File uploaded successfully", code=201)


class DashboardAssistantFileUploadDetail(
    DashboardRetrieveMixin,
    DashboardDestroyMixin,
    generics.RetrieveUpdateDestroyAPIView,
):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = AssistantFileUploadSerializer
    permission_classes = [IsDashboardUser]
    retrieve_message = "File retrieved"
    destroy_message = "File deleted"


class DashboardPromptTemplateList(DashboardListMixin, DashboardCreateMixin, generics.ListCreateAPIView):
    queryset = PromptTemplate.objects.all()
    serializer_class = DashboardPromptTemplateSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    list_message = "Prompt templates retrieved successfully"
    create_message = "Prompt template created successfully"


class DashboardPromptTemplateDetail(
    DashboardRetrieveMixin,
    DashboardPartialUpdateMixin,
    DashboardDestroyMixin,
    generics.RetrieveUpdateDestroyAPIView,
):
    queryset = PromptTemplate.objects.all()
    serializer_class = DashboardPromptTemplateSerializer
    permission_classes = [IsDashboardUser]
    retrieve_message = "Prompt template retrieved successfully"
    update_message = "Prompt template updated successfully"
    destroy_message = "Prompt template deleted successfully"
