from django.db.models import Count, Sum
from django.http import FileResponse
from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, permissions, views
from rest_framework.exceptions import NotFound

from apps.assistant.filters import LeadFilter
from apps.assistant.models import (
    Assistant,
    AssistantFileUpload,
    Conversation,
    FollowUpConfig,
    FollowUpLog,
    FollowUpStage,
    Lead,
    Message,
    PromptTemplate,
)
from apps.assistant.serializers import (
    AssistantFileUploadSerializer,
    AssistantSerializer,
    ConversationRetrieveSerializer,
    ConversationSerializer,
    FollowUpConfigSerializer,
    FollowUpLogSerializer,
    FollowUpStageSerializer,
    LeadExportSerializer,
    LeadSerializer,
    MessageBulkReadSerializer,
    MessageSerializer,
    PromptTemplateListSerializer,
    UpdateFileUploadSerializer,
)
from apps.assistant.utils import owned_assistants
from apps.shared.addons.redis import publish_new_message_to_ws
from apps.shared.addons.validations import error_response, success_response
from apps.shared.ai_service import knowledge_base


class AssistantListCreateView(generics.ListCreateAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', "user__username", "company_name"]
    ordering_fields = ['name', "user__username", "company_name"]
    ordering = ['name', "user", "company_name"]
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return owned_assistants(self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        if request.user.created_by:
            serializer.save(user=request.user.created_by, created_by=request.user)
        else:
            serializer.save(user=request.user)
        return success_response(message=_("Assistant muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class AssistantRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return owned_assistants(self.request.user)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance,context={'request': request})
        return success_response(data=serializer.data, message=_("Assistant muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data,
                                         partial=kwargs.pop('partial', False),
                                         context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # Nothing to sync remotely: the agent reads the assistant's prompt and
        # settings on every turn, so an edit applies to the next message.
        return success_response(message=_("Assistant muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user != request.user:
            return error_response(
                message=_("Faqat mijozlar o'zlarining assistantlarini o'chirishlari mumkin"),
                code=403
            )
        if request.user.created_by is not None:
            return error_response(
                message=_("Xodimlar assistantlarni o'chira olmaydi"),
                code=403
            )
        if instance.vector_id:
            knowledge_base.delete_store(instance.vector_id)
        self.perform_destroy(instance)
        return success_response(message=_("Assistant muvaffaqiyatli o'chirildi"), code=204)


class ConversationListCreateView(generics.ListCreateAPIView):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['assistant__name', 'username']
    ordering_fields = ['assistant__name', "start_time", "end_time"]
    ordering = ["-updated_time"]
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        assistant_id = self.kwargs.get("pk")
        return Conversation.objects.filter(
            assistant_id=assistant_id,
            assistant__in=owned_assistants(self.request.user),
        )

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get("pk")
        if not owned_assistants(request.user).filter(id=assistant_id).exists():
            raise NotFound(_("Assistant topilmadi"))
        serializer = self.get_serializer(data=request.data, context={'assistant_id': assistant_id, 'request': request})
        serializer.is_valid(raise_exception=True)
        conversation = serializer.save(assistant_id=assistant_id)
        data = {
            "assistant_id": assistant_id,
            "conversation_id": conversation.id,
            "thread_id": conversation.thread_id
        }
        return success_response(message=_("Conversation muvaffaqiyatli yaratildi"), data=data, code=201)


class ConversationRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Conversation.objects.all()
    serializer_class = ConversationRetrieveSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        conversation_id = self.kwargs.get('pk')
        try:
            return Conversation.objects.get(
                pk=conversation_id,
                assistant__in=owned_assistants(self.request.user),
            )
        except Conversation.DoesNotExist:
            raise NotFound(_("Conversation topilmadi"))

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Conversation muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Conversation muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Conversation muvaffaqiyatli o'chirildi"), code=204)


class MessageListCreateView(generics.ListCreateAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    # `message_content` is encrypted at rest, so an SQL `icontains` over it
    # would match nothing. Searching transcripts needs a dedicated index —
    # see docs/reports/2026-08-04-field-encryption-at-rest.md.
    search_fields = ['conversation__assistant__name']
    ordering_fields = ['conversation__assistant__name', 'created_time']
    ordering = ['conversation', 'created_time']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        conversation_id = self.kwargs.get('pk')
        return Message.objects.filter(
            conversation_id=conversation_id,
            conversation__assistant__in=owned_assistants(self.request.user),
        )

    def create(self, request, *args, **kwargs):
        conversation_id = self.kwargs.get('pk')
        if not Conversation.objects.filter(
            id=conversation_id,
            assistant__in=owned_assistants(request.user),
        ).exists():
            raise NotFound(_("Conversation topilmadi"))
        serializer = self.get_serializer(data=request.data, context={'conversation_id': conversation_id, 'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Message muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class MessageRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Message.objects.filter(
            conversation__assistant__in=owned_assistants(self.request.user),
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Message muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Message muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Message muvaffaqiyatli o'chirildi"), code=204)


class ConversationMessagesListView(generics.ListAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    # `message_content` is encrypted at rest, so an SQL `icontains` over it
    # would match nothing. Searching transcripts needs a dedicated index —
    # see docs/reports/2026-08-04-field-encryption-at-rest.md.
    search_fields = ['conversation__assistant__name']
    ordering_fields = ['conversation__assistant__name', 'created_time']
    ordering = ['conversation', 'created_time']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        conversation_id = self.kwargs.get('pk')
        return Message.objects.filter(
            conversation_id=conversation_id,
            conversation__assistant__in=owned_assistants(self.request.user),
        )


class AssistantFileUploadListCreateView(generics.ListCreateAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = AssistantFileUploadSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['assistant__name', 'filename']
    ordering_fields = ['assistant__name', 'created_time']
    ordering = ['assistant', 'created_time']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        assistant_id = self.kwargs.get('pk')
        return AssistantFileUpload.objects.filter(
            assistant_id=assistant_id,
            assistant__in=owned_assistants(self.request.user),
        )

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get('pk')
        try:
            assistant = owned_assistants(request.user).get(id=assistant_id)
        except Assistant.DoesNotExist:
            return error_response(message=_("Assistant topilmadi"), code=404)
        files = request.FILES.getlist('file')  # Handle multiple files
        serializer = self.get_serializer(
            data=request.data,
            context={'assistant': assistant, 'files': files, 'request': request}
        )
        serializer.is_valid(raise_exception=True)

        serializer.save()
        # The assistant's knowledge base (vector store) is created lazily on the
        # first upload, inside the serializer.
        return success_response(
            message=_("File muvaffaqiyatli yaratildi"),
            # Every other create in this app returns its payload; without it the
            # client never learns the new file's id.
            data=serializer.data,
            code=201,
        )


class AssistantFileUploadUpdateView(generics.CreateAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = UpdateFileUploadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get('pk')
        try:
            assistant = owned_assistants(request.user).get(id=assistant_id)
        except Assistant.DoesNotExist:
            return error_response(message=_("Assistant topilmadi"), code=404)

        files = request.FILES.getlist('file')
        context = {'assistant': assistant, 'files': files, 'request': request}

        # NOT `many=True`: the serializer takes one payload and reads the file
        # list off the context itself. With `many=True` DRF parsed the multipart
        # QueryDict as an empty list, so `save()` wrote nothing and the endpoint
        # answered 200 while silently discarding the upload.
        serializer = self.get_serializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        uploads = getattr(serializer, "uploaded_files", [serializer.instance])
        return success_response(
            message=_("File muvaffaqiyatli o'zgartirildi"),
            data=AssistantFileUploadSerializer(uploads, many=True).data,
            code=200,
        )


class AssistantFileUploadRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AssistantFileUploadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # `owned_assistants()` rather than `assistant__user=request.user`: the
        # list and upload endpoints already let a customer's staff account work
        # with these files, so scoping detail/update/delete more narrowly was an
        # inconsistency, not a control. It is still one tenant either way.
        return AssistantFileUpload.objects.filter(
            assistant__in=owned_assistants(self.request.user),
        )

    def get_object(self):
        try:
            return self.get_queryset().get(pk=self.kwargs.get('pk'))
        except AssistantFileUpload.DoesNotExist:
            raise NotFound(detail=_("Berilgan ID ga ega fayl topilmadi"))

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("File muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, context={'assistant': instance.assistant,
                                                                               'files': request.FILES.getlist('file')}, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("File muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        knowledge_base.delete_file(instance.assistant.vector_id, instance.file_id)
        instance.delete()
        return success_response(message=_("Fayl muvaffaqiyatli o'chirildi"), code=200)

class MessageBulkReadView(generics.UpdateAPIView):
    serializer_class = MessageBulkReadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def update(self, request, *args, **kwargs):
        conversation_id = kwargs.get('pk')
        if not Conversation.objects.filter(
            id=conversation_id,
            assistant__in=owned_assistants(request.user),
        ).exists():
            raise NotFound(_("Conversation topilmadi"))
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message_ids = serializer.validated_data['message_ids']

        updated_count = Message.objects.filter(
            id__in=message_ids,
            conversation__id=conversation_id,
        ).update(is_read=True)

        unread_message_count = Message.objects.filter(
            conversation__id=conversation_id,
            is_read=False
        ).count()
        last_message = Message.objects.filter(conversation__id=conversation_id).order_by('-created_time').first()
        if last_message:
            publish_new_message_to_ws(conversation_id=conversation_id, unread_message_count=unread_message_count,
                                      assistant_id=last_message.conversation.assistant.id, last_message=last_message.message_content)
        return success_response(
            message=_("Xabarlar muvaffaqiyatli o'qildi"),
            data={"updated_count": updated_count},
            code=200
        )

class LeadListCreateView(generics.ListCreateAPIView):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    filterset_class = LeadFilter
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['full_name', 'phone_number', 'email', 'product']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        assistant_id = self.kwargs.get('pk')
        return Lead.objects.filter(
            assistant_id=assistant_id,
            assistant__in=owned_assistants(self.request.user),
        )

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get('pk')
        if not owned_assistants(request.user).filter(id=assistant_id).exists():
            raise NotFound(_("Assistant topilmadi"))
        serializer = self.get_serializer(data=request.data, context={'assistant_id': assistant_id, 'request': request})
        serializer.is_valid(raise_exception=True)
        # The assistant comes from the URL (already ownership-checked above).
        # Without this the lead was saved with `assistant=NULL` — invisible to
        # the list endpoint and unreachable by id, so it could never be
        # retrieved or deleted again.
        serializer.save(assistant_id=assistant_id)
        return success_response(message=_("Lead muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class LeadRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Lead.objects.filter(
            assistant__in=owned_assistants(self.request.user),
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Lead muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Lead muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Lead muvaffaqiyatli o'chirildi"), code=204)


class ExportLeadsView(views.APIView):
    serializer_class = LeadExportSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get('pk')
        if not owned_assistants(request.user).filter(id=assistant_id).exists():
            raise NotFound(_("Assistant topilmadi"))
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Streamed straight from memory — nothing is written to the server's
        # working directory, so concurrent exports can't hand one tenant the
        # other's workbook and no files are left behind.
        filename, buffer = serializer.export_leads(assistant_id)
        return FileResponse(buffer, as_attachment=True, filename=filename)


class PromptTemplateListView(generics.ListAPIView):
    queryset = PromptTemplate.objects.filter(is_active=True)
    serializer_class = PromptTemplateListSerializer
    permission_classes = [permissions.IsAuthenticated]


class AssistantTokenStatsView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        assistants = owned_assistants(request.user)

        stats = []
        for assistant in assistants:
            token_data = Message.objects.filter(
                conversation__assistant=assistant,
                sender='assistant',
            ).aggregate(
                total_input_tokens=Sum('input_tokens'),
                total_output_tokens=Sum('output_tokens'),
                message_count=Count('id'),
            )
            stats.append({
                'assistant_id': str(assistant.id),
                'assistant_name': assistant.name,
                'company_name': assistant.company_name,
                'total_input_tokens': token_data['total_input_tokens'] or 0,
                'total_output_tokens': token_data['total_output_tokens'] or 0,
                'message_count': token_data['message_count'] or 0,
            })

        return success_response(
            data=stats,
            message=_("Assistant token statistikasi"),
            code=200,
        )


class FollowUpConfigView(generics.RetrieveUpdateAPIView):
    serializer_class = FollowUpConfigSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        assistant_id = self.kwargs.get('pk')
        # `owned_assistants()` exists to avoid exactly this: when `created_by`
        # is None the `Q(user=None)` leg matches every *ownerless* assistant.
        assistant = owned_assistants(self.request.user).filter(id=assistant_id).first()
        if not assistant:
            raise NotFound(_("Assistant topilmadi"))
        config, _created = FollowUpConfig.objects.get_or_create(
            assistant=assistant,
            defaults={'target_statuses': ['open', 'pending']},
        )
        return config

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Follow-up konfiguratsiyasi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            message=_("Follow-up konfiguratsiyasi yangilandi"),
            data=serializer.data, code=200,
        )


class FollowUpStageListCreateView(generics.ListCreateAPIView):
    serializer_class = FollowUpStageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FollowUpStage.objects.none()
        assistant_id = self.kwargs.get('pk')
        return FollowUpStage.objects.filter(
            config__assistant_id=assistant_id,
            config__assistant__in=owned_assistants(self.request.user),
        ).order_by('stage_number')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message=_("Follow-up bosqichlari"), code=200)

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get('pk')
        assistant = owned_assistants(request.user).filter(id=assistant_id).first()
        if not assistant:
            raise NotFound(_("Assistant topilmadi"))
        config, _created = FollowUpConfig.objects.get_or_create(
            assistant=assistant,
            defaults={'target_statuses': ['open', 'pending']},
        )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(config=config)
        return success_response(
            message=_("Follow-up bosqichi yaratildi"),
            data=serializer.data, code=201,
        )


class FollowUpStageDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = FollowUpStageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return FollowUpStage.objects.filter(
            config__assistant__in=owned_assistants(self.request.user),
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Follow-up bosqichi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            message=_("Follow-up bosqichi yangilandi"),
            data=serializer.data, code=200,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Follow-up bosqichi o'chirildi"), code=204)


class FollowUpLogListView(generics.ListAPIView):
    serializer_class = FollowUpLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['scheduled_at', 'sent_at', 'created_time']
    ordering = ['-scheduled_at']

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FollowUpLog.objects.none()
        assistant_id = self.kwargs.get('pk')
        queryset = FollowUpLog.objects.filter(
            conversation__assistant_id=assistant_id,
            conversation__assistant__in=owned_assistants(self.request.user),
        ).select_related('stage', 'conversation')

        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message=_("Follow-up loglari"), code=200)
