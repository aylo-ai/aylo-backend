import os

from django.utils.translation import gettext_lazy as _
from django.http import FileResponse
from django.db.models import Q
from rest_framework import permissions, filters, generics, views
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.exceptions import NotFound

from apps.assistant.models import Assistant, AssistantFileUpload, Conversation, Message, Lead
from shared.addons.validations import success_response, error_response
from shared.ai_service.openai_client import client
from shared.ai_service.assistant import assistant_service
from shared.addons.redis import publish_new_message_to_ws
from apps.assistant.filters import LeadFilter
from apps.assistant.serializers import (AssistantSerializer, 
    ConversationSerializer, 
    MessageSerializer, 
    SettingsSerializer, 
    AssistantFileUploadSerializer, 
    ConversationRetrieveSerializer, 
    UpdateFileUploadSerializer, 
    MessageBulkReadSerializer, 
    LeadSerializer, 
    LeadExportSerializer)

class AssistantListCreateView(generics.ListCreateAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', "user__username", "company_name"]
    ordering_fields = ['name', "user__username", "company_name"]
    ordering = ['name', "user", "company_name"]
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Assistant.objects.filter(
                Q(user=user.created_by) |
                Q(user=user)
            ).distinct()

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
        user = self.request.user
        return Assistant.objects.filter(
                Q(user=user.created_by) |
                Q(user=user)
            ).distinct()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance,context={'request': request})
        return success_response(data=serializer.data, message=_("Assistant muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        assistant = instance
        if assistant and assistant.assistant_id:
            success, message = assistant_service.update_assistant(assistant.assistant_id, assistant.name, assistant)
            print(f"Assistant updated successfully: {success}, {message}")
        return success_response(message=_("Assistant muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user != request.user:
            return error_response(
                message=_("Faqat mijozlar o'zlarining assistantlarini o'chirishlari mumkin"),
                code=403
            )
        assistant_id = instance.assistant_id
        vector_id = instance.vector_id
        print(f"Assistant ID: {assistant_id}")
        if assistant_id:
            assistant_service.delete_assistant(assistant_id)
        if vector_id:
            assistant_service.delete_vector_store(vector_id)
        self.perform_destroy(instance)
        return success_response(message=_("Assistant muvaffaqiyatli o'chirildi"), code=204)


class ConversationListCreateView(generics.ListCreateAPIView):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['assistant__name', 'session_id']
    ordering_fields = ['assistant__name', 'session_id', "start_time", "end_time"]
    ordering = ["-updated_time"]
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        assistant_id = self.kwargs.get("pk")
        return super().get_queryset().filter(assistant_id=assistant_id)

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get("pk")
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
        return self.queryset.get(pk=conversation_id)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Conversation muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
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
    search_fields = ['conversation__assistant__name', 'message']
    ordering_fields = ['conversation__assistant__name', 'created_time']
    ordering = ['conversation', 'created_time']
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        conversation_id = self.kwargs.get('pk')
        return super().get_queryset().filter(conversation_id=conversation_id)

    def create(self, request, *args, **kwargs):
        conversation_id = self.kwargs.get('pk')
        serializer = self.get_serializer(data=request.data, context={'conversation_id': conversation_id, 'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Message muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class MessageRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Message muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
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
    search_fields = ['conversation__assistant__name', 'message']
    ordering_fields = ['conversation__assistant__name', 'created_time']
    ordering = ['conversation', 'created_time']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        conversation_id = self.kwargs.get('pk')
        print(f"Conversation ID: {conversation_id}")
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
        return success_response(message=_("Settings muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class SettingsRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = SettingsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Settings muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Settings muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Settings muvaffaqiyatli o'chirildi"), code=204)


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
            return error_response(message=_("Assistant topilmadi"), code=404)
        files = request.FILES.getlist('file')  # Handle multiple files
        serializer = self.get_serializer(
            data=request.data,
            context={'assistant': assistant, 'files': files, 'request': request}
        )
        serializer.is_valid(raise_exception=True)

        serializer.save()
        if assistant and not assistant.vector_id:
            success, message = assistant_service.create_assistant_and_vector_id(assistant, request)
            if not success:
                return error_response(message=message, code=400)
            print("saved assistant data")
        return success_response(message=_("File muvaffaqiyatli yaratildi"), code=201)
    

class AssistantFileUploadUpdateView(generics.CreateAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = UpdateFileUploadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get('pk')
        try:
            assistant = Assistant.objects.get(id=assistant_id)
        except Assistant.DoesNotExist:
            return error_response(message=_("Assistant topilmadi"), code=404)

        files = request.FILES.getlist('file')
        context = {'assistant': assistant, 'files': files, 'request': request}

        serializer = self.get_serializer(data=request.data, context=context, many=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("File muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)


class AssistantFileUploadRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = AssistantFileUploadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        try:
            return self.queryset.get(pk=self.kwargs.get('pk'), assistant__user=self.request.user)
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
        pk = kwargs.get("pk")
        try:
            instance = AssistantFileUpload.objects.get(id=pk, assistant__user=request.user)
        except AssistantFileUpload.DoesNotExist:
            return error_response(message=_("Fayl topilmadi"), code=404)

        assistant = instance.assistant
        if assistant and getattr(assistant, "vector_id", None) and getattr(instance, "file_id", None):
            try:
                
                client.vector_stores.files.delete(
                    vector_store_id=assistant.vector_id,
                    file_id=instance.file_id
                )
            except Exception as e:
                print(f"[-] Failed removing file from vector store: {e}")
        instance.delete()
        return success_response(message=_("Fayl muvaffaqiyatli o'chirildi"), code=200)

class MessageBulkReadView(generics.UpdateAPIView):
    serializer_class = MessageBulkReadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def update(self, request, *args, **kwargs):
        conversation_id = kwargs.get('pk')
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
        publish_new_message_to_ws(conversation_id=conversation_id, unread_message_count=unread_message_count, 
                                  assistant_id=last_message.conversation.assistant.id, last_message=last_message.message_content)
        print(f"Published new message to WS for conversation {conversation_id}")
        return success_response(
            message=_("Xabarlar muvaffaqiyatli o'qildi"),
            data={"updated_count": updated_count},
            code=200
        )

# class AssistantFileGoogleDocView(generics.CreateAPIView):
#     serializer_class = AssistantFileGoogleDocSerializer
#     permission_classes = [permissions.IsAuthenticated]

#     def create(self, request, *args, **kwargs):
#         serializer = self.get_serializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
#         serializer.save()
#         return success_response(message=_("Assistant google sheet muvaffaqiyatli yaratildi"), data=serializer.data, code=201)

class LeadListCreateView(generics.ListCreateAPIView):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    filterset_class = LeadFilter
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['full_name', 'phone_number', 'email', 'product']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        assistant_id = self.kwargs.get('pk')
        return super().get_queryset().filter(assistant_id=assistant_id)
    
    def create(self, request, *args, **kwargs):
        assistant_id = self.kwargs.get('pk')
        serializer = self.get_serializer(data=request.data, context={'assistant_id': assistant_id, 'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Lead muvaffaqiyatli yaratildi"), data=serializer.data, code=201)
    

class LeadRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        lead_id = self.kwargs.get('pk')
        return super().get_queryset().filter(id=lead_id)
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Lead muvaffaqiyatli olindi"), code=200)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
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
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_path = serializer.export_leads(assistant_id)
        response = FileResponse(open(file_path, 'rb'), as_attachment=True, filename=os.path.basename(file_path))
        return response