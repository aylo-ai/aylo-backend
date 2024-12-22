from django.db.models import Max
from rest_framework import permissions, filters, generics

from apps.assistant.models import Assistant, AssistantFileUpload, Conversation, Message
from apps.assistant.serializers import AssistantSerializer, ConversationSerializer, MessageSerializer, \
    SettingsSerializer, AssistantFileUploadSerializer, ConversationRetrieveSerializer
from shared.addons.validations import success_response, error_response


class AssistantListCreateView(generics.ListCreateAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', "user__username", "company_name"]
    ordering_fields = ['name', "user__username", "company_name"]
    ordering = ['name', "user", "company_name"]
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Assistant.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return success_response(message='Assistant created successfully', data=serializer.data, code=201)


class AssistantRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message='Assistant retrieved successfully', code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message='Assistant updated successfully', data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message='Assistant deleted successfully', code=204)


class ConversationListCreateView(generics.ListCreateAPIView):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['assistant__name', 'session_id']
    ordering_fields = ['assistant__name', 'session_id']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        assistant_id = self.kwargs.get("pk")
        return super().get_queryset()\
            .filter(assistant_id=assistant_id)\
            .annotate(latest_message_time=Max('messages__created_time'))\
            .order_by('-latest_message_time')  # Order by the latest message time

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get("pk")
        serializer = self.get_serializer(data=request.data, context={'assistant_id': assistant_id})
        serializer.is_valid(raise_exception=True)
        thread_id, conversation = serializer.save(assistant_id=assistant_id)
        data = {
            "assistant_id": assistant_id,
            "conversation_id": conversation.id,
            "thread_id": thread_id
        }
        return success_response(message='Conversation created successfully', data=data, code=201)


class ConversationRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Conversation.objects.all()
    serializer_class = ConversationRetrieveSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        conversation_id = self.kwargs.get('pk')
        return self.queryset.get(pk=conversation_id)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message='Conversation retrieved successfully', code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message='Conversation updated successfully', data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message='Conversation deleted successfully', code=204)


class MessageListCreateView(generics.ListCreateAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['conversation__assistant__name', 'message']
    ordering_fields = ['conversation__assistant__name', 'created_time']
    ordering = ['conversation', 'created_time']
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        conversation_id = self.kwargs.get('pk')
        return super().get_queryset().filter(conversation_id=conversation_id)

    def create(self, request, *args, **kwargs):
        conversation_id = self.kwargs.get('pk')
        serializer = self.get_serializer(data=request.data, context={'conversation_id': conversation_id})
        serializer.is_valid(raise_exception=True)
        serializer.save(conversation_id=conversation_id)
        return success_response(message='Message created successfully', data=serializer.data, code=201)


class MessageRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message='Message retrieved successfully', code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message='Message updated successfully', data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message='Message deleted successfully', code=204)


class ConversationMessagesListView(generics.ListAPIView):
    queryset = Assistant.objects.all()
    serializer_class = MessageSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['conversation__assistant__name', 'message']
    ordering_fields = ['conversation__assistant__name', 'created_time']
    ordering = ['conversation', 'created_time']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        conversation_id = self.kwargs.get('pk')
        return self.queryset.filter(conversation_id=conversation_id)


class SettingsListCreateView(generics.ListCreateAPIView):
    queryset = Assistant.objects.all()
    serializer_class = SettingsSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['assistant__name']
    ordering_fields = ['assistant__name']
    ordering = ['assistant']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message='Settings created successfully', data=serializer.data, code=201)


class SettingsRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = SettingsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message='Settings retrieved successfully', code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message='Settings updated successfully', data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message='Settings deleted successfully', code=204)


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
        return self.queryset.filter(assistant_id=assistant_id)

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get('pk')
        try:
            assistant = Assistant.objects.get(id=assistant_id)
        except Assistant.DoesNotExist:
            return error_response(message="Assistant not found", code=404)
        files = request.FILES.getlist('file')  # Handle multiple files
        serializer = self.get_serializer(
            data=request.data,
            context={'assistant': assistant, 'files': files, 'request': request}
        )
        serializer.is_valid(raise_exception=True)

        serializer.save()
        return success_response(message='File uploaded successfully', code=201)


class AssistantFileUploadRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = AssistantFileUploadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.queryset.get(pk=self.kwargs.get('pk'), assistant__user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message='File retrieved successfully', code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message='File updated successfully', data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message='File deleted successfully', code=204)