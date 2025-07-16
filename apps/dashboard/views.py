from rest_framework import generics, filters
from rest_framework.views import APIView

from apps.dashboard.filters import UserFilter
from apps.user.models import User
from apps.user.serializers import UserSerializer
from apps.assistant.serializers import AssistantSerializer, ConversationSerializer, MessageSerializer, AssistantFileUploadSerializer
from apps.assistant.models import Assistant, Conversation, Message, AssistantFileUpload
from apps.payment.models import Transaction, Subscription, Balance, Card, Feature, PricingPackage
from apps.payment.serializers import TransactionSerializer, SubscriptionSerializer, BalanceSerializer, CardSerializer, FeatureSerializer, PricingPackageSerializer
from apps.integration.models import InstagramCommentResponse, Integration
from apps.integration.serializers import InstagramCommentResponseSerializer, IntegrationSerializer
from apps.user.models import Notification
from apps.user.serializers import NotificationSerializer
from apps.shared.permissions import IsAdmin, IsAuthenticated
from apps.shared.addons.enums import UserRoles
from apps.shared.pagination import StandardResultsSetPagination
from apps.dashboard.serializers import (
    DashboardConversationSerializer, 
    DashboardSendOtpLoginSerializer, 
    DashboardVerifyOtpLoginSerializer,
    DashboardSerializer,
    DashboardUserSerializer,
    DashboardStatisticsSerializer
)

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

    
    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Users retrieved successfully", code=200)
    
class DashboardUserDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    serializer_class = DashboardUserSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return User.objects.get(id=pk)
    
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset())
        return success_response(data=serializer.data, message="User retrieved successfully", code=200)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="User updated successfully", code=200)    
    
    def destroy(self, request, *args, **kwargs):
        self.get_queryset().delete()
        return success_response(message="User deleted successfully", code=200)
    

class DashboardAssistantList(generics.ListAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.queryset, many=True)
        return success_response(data=serializer.data, message="Assistants retrieved successfully", code=200)
    
class DashboardAssistantDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Assistant.objects.filter(id=pk)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Assistant updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message="Assistant deleted successfully", code=200)
    
    
class DashboardConversationList(generics.ListAPIView):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Conversations retrieved successfully", code=200)
    

class DashboardConversationDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Conversation.objects.all()
    serializer_class = DashboardConversationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Conversation.objects.filter(id=pk)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Conversation updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message="Conversation deleted successfully", code=200)
    
    
class DashboardMessageList(generics.ListAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination

    
    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Messages retrieved successfully", code=200)
    
    
class DashboardCommentResponseList(generics.ListAPIView):
    queryset = InstagramCommentResponse.objects.all()
    serializer_class = InstagramCommentResponseSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Comment responses retrieved successfully", code=200)
    
   
class DashboardIntegrationList(generics.ListAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Integrations retrieved successfully", code=200)
    
class DashboardIntegrationDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Integration.objects.filter(id=pk)
    
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset())
        return success_response(data=serializer.data, message="Integration retrieved successfully", code=200)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Integration updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_queryset().delete()
        return success_response(message="Integration deleted successfully", code=200)
    

class DashboardNotificationList(generics.ListAPIView):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination


    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Notifications retrieved successfully", code=200)
    

class DashboardTransactionList(generics.ListAPIView):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination


    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Transactions retrieved successfully", code=200)
    

class DashboardTransactionDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAdmin, IsAuthenticated]

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Transaction.objects.filter(id=pk)
    
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset())
        return success_response(data=serializer.data, message="Transaction retrieved successfully", code=200)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Transaction updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_queryset().delete()
        return success_response(message="Transaction deleted successfully", code=200)
    

class DashboardSubscriptionList(generics.ListAPIView):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Subscriptions retrieved successfully", code=200)
    

class DashboardSubscriptionDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Subscription.objects.filter(id=pk)
    
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset())
        return success_response(data=serializer.data, message="Subscription retrieved successfully", code=200)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Subscription updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_queryset().delete()
        return success_response(message="Subscription deleted successfully", code=200)
    
    
    
class DashboardBalanceList(generics.ListAPIView):
    queryset = Balance.objects.all()
    serializer_class = BalanceSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Balances retrieved successfully", code=200)
    
    
class DashboardAssistantFileUploadList(generics.ListAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = AssistantFileUploadSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    
    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Assistant file uploads retrieved successfully", code=200)
    
class DashboardAssistantFileUploadDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = AssistantFileUploadSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return AssistantFileUpload.objects.filter(id=pk)
    
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset())
        return success_response(data=serializer.data, message="Assistant file upload retrieved successfully", code=200)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Assistant file upload updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_queryset().delete()
        return success_response(message="Assistant file upload deleted successfully", code=200)
    

class DashboardCardList(generics.ListAPIView):
    queryset = Card.objects.all()
    serializer_class = CardSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    
    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.queryset, many=True)
        return success_response(data=serializer.data, message="Cards retrieved successfully", code=200)
    

class DashboardFeatureList(generics.ListAPIView):
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.queryset, many=True)
        return success_response(data=serializer.data, message="Features retrieved successfully", code=200)
    
    
class DashboardFeatureDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Feature.objects.filter(id=pk)
    
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset())
        return success_response(data=serializer.data, message="Feature retrieved successfully", code=200)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Feature updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_queryset().delete()
        return success_response(message="Feature deleted successfully", code=200)
    

class DashboardPricingPackageList(generics.ListAPIView):
    queryset = PricingPackage.objects.all()
    serializer_class = PricingPackageSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return PricingPackage.objects.filter(id=pk)

    
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset())
        return success_response(data=serializer.data, message="Pricing package retrieved successfully", code=200)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Pricing package updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_queryset().delete()
        return success_response(message="Pricing package deleted successfully", code=200)
    
class DashboardPricingPackageDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = PricingPackage.objects.all()
    serializer_class = PricingPackageSerializer
    permission_classes = [IsAdmin, IsAuthenticated]
    
    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return PricingPackage.objects.filter(id=pk)
    
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset())
        return success_response(data=serializer.data, message="Pricing package retrieved successfully", code=200)
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()   
        return success_response(data=serializer.data, message="Pricing package updated successfully", code=200)
    
    def destroy(self, request, *args, **kwargs):
        self.get_queryset().delete()
        return success_response(message="Pricing package deleted successfully", code=200)
    
    
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
    
class DashboardView(APIView):
    serializer_class = DashboardSerializer
    permission_classes = [IsAdmin, IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return success_response(data=serializer.data, message="Dashboard data retrieved successfully", code=200)
    

class DashboardStatisticsView(APIView):
    serializer_class = DashboardStatisticsSerializer
    permission_classes = [IsAdmin, IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return success_response(data=serializer.data, message="Dashboard statistics retrieved successfully", code=200)

