from rest_framework import generics, filters
from rest_framework.views import APIView
from apps.user.models import User
from apps.user.serializers import UserSerializer
from apps.assistant.serializers import AssistantSerializer, ConversationSerializer, MessageSerializer, AssistantFileUploadSerializer
from apps.assistant.models import Assistant, Conversation, Message, AssistantFileUpload
from apps.payment.models import Transaction, Subscription, Balance, RetryPayment, Card
from apps.payment.serializers import TransactionSerializer, SubscriptionSerializer, BalanceSerializer, RetryPaymentSerializer, CardSerializer
from apps.integration.models import InstagramCommentResponse, Integration
from apps.integration.serializers import InstagramCommentResponseSerializer, IntegrationSerializer
from apps.user.models import Notification
from apps.user.serializers import NotificationSerializer
from apps.shared.permissions import IsAdmin, IsAuthenticated
from apps.shared.addons.enums import UserRoles
from apps.shared.pagination import StandardResultsSetPagination
from apps.dashboard.serializers import DashboardConversationSerializer, DashboardSendOtpLoginSerializer, DashboardVerifyOtpLoginSerializer
from apps.shared.addons.validations import success_response, error_response
from apps.shared.addons.verification import send_code, verify_code_cache
from apps.shared.addons.enums import UserRoles

from rest_framework.throttling import AnonRateThrottle

class DashboardUserList(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return User.objects.filter(user_role=UserRoles.CUSTOMER.value)

class DashboardAssistantList(generics.ListAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Assistant.objects.filter(user_id=pk)
    
class DashboardConversationList(generics.ListAPIView):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Conversation.objects.filter(assistant_id=pk)
    

class DashboardConversationDetail(generics.RetrieveAPIView):
    queryset = Conversation.objects.all()
    serializer_class = DashboardConversationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Conversation.objects.filter(id=pk)

class DashboardMessageList(generics.ListAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Message.objects.filter(conversation_id=pk)
    

class DashboardCommentResponseList(generics.ListAPIView):
    queryset = InstagramCommentResponse.objects.all()
    serializer_class = InstagramCommentResponseSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return InstagramCommentResponse.objects.filter(integration_id=pk)
    

    
class DashboardIntegrationList(generics.ListAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def get_queryset(self):
        return Integration.objects.filter(assistant_id=self.kwargs.get("pk"))
    

class DashboardNotificationList(generics.ListAPIView):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def get_queryset(self):
        return Notification.objects.filter(user_id=self.kwargs.get("pk"))
    
class DashboardMessageDetail(generics.RetrieveAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Message.objects.filter(id=pk)


class DashboardTransactionList(generics.ListAPIView):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def get_queryset(self):
        return Transaction.objects.filter(user_id=self.kwargs.get("pk"))
    

class DashboardTransactionDetail(generics.RetrieveAPIView):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        return Transaction.objects.filter(id=self.kwargs.get("pk"))
    

class DashboardSubscriptionList(generics.ListAPIView):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    

class DashboardSubscriptionDetail(generics.RetrieveAPIView):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        return Subscription.objects.filter(id=self.kwargs.get("pk"))
    
class DashboardBalanceList(generics.ListAPIView):
    queryset = Balance.objects.all()
    serializer_class = BalanceSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        return Balance.objects.filter(user_id=self.kwargs.get("pk"))
    
class DashboardRetryPaymentList(generics.ListAPIView):
    queryset = RetryPayment.objects.all()
    serializer_class = RetryPaymentSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        return RetryPayment.objects.filter(subscription_id=self.kwargs.get("pk"))
    
class DashboardAssistantFileUploadList(generics.ListAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = AssistantFileUploadSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        return AssistantFileUpload.objects.filter(assistant_id=self.kwargs.get("pk"))
    

class DashboardCardList(generics.ListAPIView):
    queryset = Card.objects.all()
    serializer_class = CardSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        return Card.objects.filter(user_id=self.kwargs.get("pk"))


class DashboardSendOtpLoginView(APIView):
    serializer_class = DashboardSendOtpLoginSerializer
    throttle_classes = (AnonRateThrottle,)

    def post(self, request, *args, **kwargs):
        
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.data.get("phone_number")
        user = User.objects.filter(phone_number=phone_number).first()
        if user:
            if user.user_role == UserRoles.ADMIN.value:
                success, message = send_code(phone_number)
            else:
                return error_response(message=("Siz admin emassiz"), code=400)
        else:
            return error_response(message=("Bizda bunday foydalanuvchi topilmadi"), code=400)
            
        if success:
            return success_response(data=serializer.data, message=message, code=200)
        return error_response(message=message, code=400)

class DashboardVerifyOtpLoginView(APIView):
    serializer_class = DashboardVerifyOtpLoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.data.get("phone_number")
        code = serializer.data.get("code")
        
        if phone_number:
            success, message = verify_code_cache(phone_number, code)
        else:
            return error_response(message=("Telefon raqam yoki email kiritilmagan"), code=400)
        if success:
            return success_response(data=serializer.data, message=message, code=200)
        return error_response(message=message, code=400)