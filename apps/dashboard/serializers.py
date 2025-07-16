from rest_framework import serializers
from django.db.models import Sum

from apps.assistant.models import Conversation, Assistant, Message
from apps.assistant.serializers import AssistantSerializer
from apps.integration.serializers import IntegrationSerializer
from apps.payment.models import Transaction
from apps.payment.serializers import TransactionSerializer
from apps.shared.addons.enums import SenderTypes, UserRoles, PaymentStatuses, MessageTypes
from apps.user.models import User


class DashboardConversationSerializer(serializers.ModelSerializer):
    message_price = serializers.SerializerMethodField(method_name="get_message_price")
    
    class Meta:
        model = Conversation
        fields = [
            'id',
            'assistant',
            'status',
            'thread_id',
            'platform',
            'start_time',
            'end_time',
            'created_time',
            'updated_time',
            "message_price",
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_message_price(self, obj):
        message_count = obj.messages.count()
        message_output = obj.messages.filter(sender=SenderTypes.ASSISTANT.value)
        message_input = sum([message.input_tokens for message in message_output])
        message_output = sum([message.output_tokens for message in message_output])

        return {
            "message_price": f"${(message_input/1000000 * 5) + (message_output/1000000 * 20):.2f}",
            "message_count": message_count,
        }

    
class DashboardSendOtpLoginSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True)

    def validate(self, attrs):
        phone_number = attrs.get("phone_number")
        if not phone_number:
            raise serializers.ValidationError("Telefon raqam kiritilmagan")
        return attrs
    
class DashboardVerifyOtpLoginSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True)
    code = serializers.CharField(required=True)
    
    def validate(self, attrs):
        phone_number = attrs.get("phone_number")
        code = attrs.get("code")
        user = User.objects.filter(phone_number=phone_number).first()
        if not user:
            raise serializers.ValidationError("Bizda bunday foydalanuvchi topilmadi")
        if user.user_role != UserRoles.ADMIN.value:
            raise serializers.ValidationError("Telefon raqam bilan login qiling")

        if not phone_number:
            raise serializers.ValidationError("Telefon raqam kiritilmagan")
        if not code:
            raise serializers.ValidationError("Code kiritilmagan")
        return attrs

    def get_tokens(self): # noqa
        phone_number = self.validated_data.get('phone_number', None)
        if phone_number:
            user = User.objects.filter(phone_number=phone_number).first()
        if user:
            return user.tokens()
        return None
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['tokens'] = self.get_tokens()
        return data
    
class DashboardSerializer(serializers.Serializer):
    assistants_count = serializers.SerializerMethodField(method_name="get_assistants_count")
    users_count = serializers.SerializerMethodField(method_name="get_users_count")
    conversations_count = serializers.SerializerMethodField(method_name="get_conversations_count")
    transactions_price = serializers.SerializerMethodField(method_name="get_transactions_price")
    ai_token_price = serializers.SerializerMethodField(method_name="get_ai_token_price")

    class Meta:
        fields = [
            "assistants_count",
            "users_count",
            "conversations_count",
            "transactions_price",
            "ai_token_price",
        ]
    def get_assistants_count(self, obj):
        return Assistant.objects.filter(is_active=True).count()
    
    def get_users_count(self, obj):
        return User.objects.filter(is_active=True).count()
    
    def get_conversations_count(self, obj):
        return Conversation.objects.count()
    
    def get_transactions_price(self, obj):
        return Transaction.objects.filter(status=PaymentStatuses.SUCCESS.value).aggregate(total_price=Sum('amount'))['total_price'] or 0
    
    def get_ai_token_price(self, obj):
        open_ai_price = 0
        gemini_ai_price = 0
        input_token = (Message.objects.filter(message_type=MessageTypes.TEXT.value, sender=SenderTypes.ASSISTANT.value)
            .aggregate(total_input_token=Sum('input_tokens'))['total_input_token'] or 0)
        output_token = (Message.objects.filter(message_type=MessageTypes.TEXT.value, sender=SenderTypes.ASSISTANT.value)
            .aggregate(total_output_token=Sum('output_tokens'))['total_output_token'] or 0)
        audio_input_token = (Message.objects.filter(message_type=MessageTypes.AUDIO.value, sender=SenderTypes.ASSISTANT.value)
            .aggregate(total_input_token=Sum('input_tokens'))['total_input_token'] or 0)
        audio_output_token = (Message.objects.filter(message_type=MessageTypes.AUDIO.value, sender=SenderTypes.ASSISTANT.value)
            .aggregate(total_output_token=Sum('output_tokens'))['total_output_token'] or 0)
        open_ai_price = (input_token/1000000 * 2.5) + (output_token/1000000 * 10)
        gemini_ai_price = (audio_input_token/1000000 * 0.5) + (audio_output_token/1000000 * 0.6)

        response = {
            "open_ai_price": f"${open_ai_price:.2f}",
            "gemini_ai_price": f"${gemini_ai_price:.2f}",
        }
        return response

class DashboardTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            'id',
            'user',
            'amount',
            'status',
            'currency',
            'transaction_type',
            'payment_method',
            'payment_details',
            'error_message',
            'refund_amount',
            'refund_date',
            'created_time',
            'updated_time',
        ]

class DashboardUserSerializer(serializers.ModelSerializer):
    subscription = serializers.SerializerMethodField(method_name="get_subscription")
    assistants = serializers.SerializerMethodField(method_name="get_assistants")
    integrations = serializers.SerializerMethodField(method_name="get_integrations")
    transactions = serializers.SerializerMethodField(method_name="get_transactions")

    class Meta:
        model = User
        fields = [
            'id',
            'first_name',
            'last_name',
            'phone_number',
            'email',
            'user_role',
            'is_active',
            'subscription',
            'assistants',
            'integrations',
            'transactions',
            'created_time',
            'updated_time',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_subscription(self, obj): # noqa
        subscription = obj.subscription
        if subscription:
            return {
                "id": subscription.id,
                "pricing_package": {
                    "id": subscription.pricing_package.id,
                    "name": subscription.pricing_package.name,
                    "type": subscription.pricing_package.type,
                    "price": subscription.pricing_package.price,
                    "request_count": subscription.pricing_package.request_count,
                    "duration_days": subscription.pricing_package.duration_days,
                    "discount_price": subscription.pricing_package.discount_price,
                    "currency": subscription.pricing_package.currency,
                },
                "start_date": subscription.start_date,
                "end_date": subscription.end_date,
                "status": subscription.status,
                "remained_request_count": subscription.remained_request_count,
                "next_payment_date": subscription.next_payment_date,
                "auto_renew": subscription.auto_renew,
                "cancellation_reason": subscription.cancellation_reason,
                "last_payment_date": subscription.last_payment_date,
                "grace_period_days": subscription.grace_period_days,
            }
        return None
    
    def get_assistants(self, obj): # noqa
        assistants = obj.assistants.all()
        return AssistantSerializer(assistants, many=True).data
    
    def get_integrations(self, obj): # noqa
        assistants = obj.assistants.all()
        integrations = []
        for assistant in assistants:
            integrations.extend(assistant.integrations.all())
        return IntegrationSerializer(integrations, many=True).data
    
    def get_transactions(self, obj): # noqa
        transactions = obj.transactions.all()
        return DashboardTransactionSerializer(transactions, many=True).data
