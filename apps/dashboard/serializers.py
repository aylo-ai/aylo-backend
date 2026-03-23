from rest_framework import serializers
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from django.db.models.functions import TruncDay, TruncMonth
from django.db.models import Min

from apps.assistant.models import Conversation, Assistant, Message, PromptTemplate, Lead
from apps.assistant.serializers import AssistantSerializer, MessageSerializer
from apps.integration.serializers import IntegrationSerializer
from apps.payment.models import Transaction, Subscription
from apps.dashboard.models import AuditLog
from apps.shared.addons.enums import SenderTypes, UserRoles, PaymentStatuses, MessageTypes, ConversationStatuses
from apps.user.models import User
from apps.shared.addons.validations import raise_validation_error


class DashboardConversationSerializer(serializers.ModelSerializer):
    message_price = serializers.SerializerMethodField(method_name="get_message_price")
    messages = serializers.SerializerMethodField(method_name="get_messages")
    assistant_name = serializers.CharField(source='assistant.name', read_only=True)
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'assistant', 'assistant_name', 'status', 'thread_id',
            'platform', 'start_time', 'end_time', 'username',
            'client_full_name', 'client_phone_email',
            'messages', 'message_count', 'created_time', 'updated_time',
            'message_price',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_message_price(self, obj):
        message_count = obj.messages.count()
        assistant_msgs = obj.messages.filter(sender=SenderTypes.ASSISTANT.value)
        message_input = sum([m.input_tokens for m in assistant_msgs])
        message_output = sum([m.output_tokens for m in assistant_msgs])
        return {
            "message_price": f"${(message_input/1000000 * 5) + (message_output/1000000 * 20):.2f}",
            "message_count": message_count,
        }

    def get_messages(self, obj):
        return MessageSerializer(obj.messages.all(), many=True).data

    def get_message_count(self, obj):
        return obj.messages.count()


class DashboardConversationListSerializer(serializers.ModelSerializer):
    """Lighter serializer for list views without full message data."""
    assistant_name = serializers.CharField(source='assistant.name', read_only=True)
    owner_name = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'assistant', 'assistant_name', 'owner_name', 'status',
            'platform', 'username', 'client_full_name', 'client_phone_email',
            'message_count', 'start_time', 'end_time',
            'created_time', 'updated_time',
        ]

    def get_message_count(self, obj):
        return obj.messages.count()

    def get_owner_name(self, obj):
        user = obj.assistant.user
        if user:
            return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username
        return None


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
        from apps.shared.permissions import DASHBOARD_ROLES
        phone_number = attrs.get("phone_number")
        code = attrs.get("code")
        user = User.objects.filter(phone_number=phone_number).first()
        if not user:
            raise serializers.ValidationError("Bizda bunday foydalanuvchi topilmadi")
        if user.user_role not in DASHBOARD_ROLES:
            raise serializers.ValidationError("Sizda dashboard huquqi yo'q")
        if not phone_number:
            raise serializers.ValidationError("Telefon raqam kiritilmagan")
        if not code:
            raise serializers.ValidationError("Code kiritilmagan")
        return attrs

    def get_tokens(self):
        phone_number = self.validated_data.get('phone_number', None)
        if phone_number:
            user = User.objects.filter(phone_number=phone_number).first()
        if user:
            return user.tokens()
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['tokens'] = self.get_tokens()
        # Include user info for frontend
        phone_number = self.validated_data.get('phone_number')
        user = User.objects.filter(phone_number=phone_number).first()
        if user:
            data['user'] = {
                'id': str(user.id),
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'phone_number': user.phone_number,
                'user_role': user.user_role,
            }
        return data


class DashboardSerializer(serializers.Serializer):
    assistants_count = serializers.SerializerMethodField()
    users_count = serializers.SerializerMethodField()
    conversations_count = serializers.SerializerMethodField()
    transactions_price = serializers.SerializerMethodField()
    ai_token_price = serializers.SerializerMethodField()

    class Meta:
        fields = [
            "assistants_count", "users_count", "conversations_count",
            "transactions_price", "ai_token_price",
        ]

    def get_assistants_count(self, obj):
        return Assistant.objects.filter(is_active=True).count()

    def get_users_count(self, obj):
        return User.objects.filter(is_active=True).count()

    def get_conversations_count(self, obj):
        return Conversation.objects.count()

    def get_transactions_price(self, obj):
        return Transaction.objects.filter(
            status=PaymentStatuses.SUCCESS.value
        ).aggregate(total_price=Sum('amount'))['total_price'] or 0

    def get_ai_token_price(self, obj):
        text_msgs = Message.objects.filter(
            message_type=MessageTypes.TEXT.value,
            sender=SenderTypes.ASSISTANT.value
        )
        audio_msgs = Message.objects.filter(
            message_type=MessageTypes.AUDIO.value,
            sender=SenderTypes.ASSISTANT.value
        )
        input_token = text_msgs.aggregate(t=Sum('input_tokens'))['t'] or 0
        output_token = text_msgs.aggregate(t=Sum('output_tokens'))['t'] or 0
        audio_input = audio_msgs.aggregate(t=Sum('input_tokens'))['t'] or 0
        audio_output = audio_msgs.aggregate(t=Sum('output_tokens'))['t'] or 0

        return {
            "open_ai_price": f"${(input_token/1000000 * 2.5) + (output_token/1000000 * 10):.2f}",
            "gemini_ai_price": f"${(audio_input/1000000 * 0.5) + (audio_output/1000000 * 0.6):.2f}",
        }


class DashboardEnhancedStatsSerializer(serializers.Serializer):
    """Enhanced dashboard statistics with period comparison and alerts."""

    def to_representation(self, instance):
        now = timezone.now()
        today = now.date()
        thirty_days_ago = today - timezone.timedelta(days=30)
        sixty_days_ago = today - timezone.timedelta(days=60)

        # Current period stats
        current_revenue = Transaction.objects.filter(
            status=PaymentStatuses.SUCCESS.value,
            created_time__date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        prev_revenue = Transaction.objects.filter(
            status=PaymentStatuses.SUCCESS.value,
            created_time__date__gte=sixty_days_ago,
            created_time__date__lt=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        current_users = User.objects.filter(created_time__date__gte=thirty_days_ago).count()
        prev_users = User.objects.filter(
            created_time__date__gte=sixty_days_ago,
            created_time__date__lt=thirty_days_ago
        ).count()

        current_conversations = Conversation.objects.filter(
            created_time__date__gte=thirty_days_ago
        ).count()

        active_assistants = Assistant.objects.filter(is_active=True).count()
        total_users = User.objects.filter(is_active=True).count()
        total_conversations = Conversation.objects.count()

        # AI costs
        text_msgs = Message.objects.filter(
            message_type=MessageTypes.TEXT.value,
            sender=SenderTypes.ASSISTANT.value
        )
        input_tokens = text_msgs.aggregate(t=Sum('input_tokens'))['t'] or 0
        output_tokens = text_msgs.aggregate(t=Sum('output_tokens'))['t'] or 0
        total_ai_cost = (input_tokens/1000000 * 2.5) + (output_tokens/1000000 * 10)

        # Alerts
        failed_payments = Transaction.objects.filter(
            status=PaymentStatuses.FAILED.value,
            created_time__date__gte=today - timezone.timedelta(days=7)
        ).count()

        escalated_conversations = Conversation.objects.filter(
            status=ConversationStatuses.ESCALATED.value
        ).count()

        open_conversations = Conversation.objects.filter(
            status=ConversationStatuses.OPEN.value
        ).count()

        expiring_subscriptions = Subscription.objects.filter(
            status='active',
            end_date__lte=today + timezone.timedelta(days=7),
            end_date__gte=today
        ).count()

        # Recent activity
        recent_transactions = Transaction.objects.select_related('user').order_by(
            '-created_time'
        )[:5]
        recent_users = User.objects.order_by('-created_time')[:5]

        return {
            'metrics': {
                'total_revenue': float(Transaction.objects.filter(
                    status=PaymentStatuses.SUCCESS.value
                ).aggregate(total=Sum('amount'))['total'] or 0),
                'revenue_30d': float(current_revenue),
                'revenue_change': self._calc_change(current_revenue, prev_revenue),
                'total_users': total_users,
                'new_users_30d': current_users,
                'users_change': self._calc_change(current_users, prev_users),
                'total_conversations': total_conversations,
                'conversations_30d': current_conversations,
                'active_assistants': active_assistants,
                'total_ai_cost': f"${total_ai_cost:.2f}",
            },
            'alerts': {
                'failed_payments': failed_payments,
                'escalated_conversations': escalated_conversations,
                'open_conversations': open_conversations,
                'expiring_subscriptions': expiring_subscriptions,
            },
            'recent_activity': {
                'transactions': [
                    {
                        'id': str(t.id),
                        'amount': float(t.amount),
                        'status': t.status,
                        'user_name': f"{t.user.first_name or ''} {t.user.last_name or ''}".strip() if t.user else 'Unknown',
                        'created_time': t.created_time.isoformat(),
                    }
                    for t in recent_transactions
                ],
                'users': [
                    {
                        'id': str(u.id),
                        'name': f"{u.first_name or ''} {u.last_name or ''}".strip() or u.username,
                        'email': u.email,
                        'created_time': u.created_time.isoformat(),
                    }
                    for u in recent_users
                ],
            },
        }

    def _calc_change(self, current, previous):
        if previous == 0:
            return 100 if current > 0 else 0
        return round(((float(current) - float(previous)) / float(previous)) * 100, 1)


class DashboardStatisticsSerializer(serializers.Serializer):
    type_filter = serializers.CharField(required=False)
    date_filter = serializers.CharField(required=False)
    statistics = serializers.SerializerMethodField()

    def get_statistics(self, obj):
        type_filter = self.context.get("type_filter", None)
        date_filter = self.context.get("date_filter", None)
        if type_filter == "transaction":
            return self.get_transaction_date_count(date_filter)
        elif type_filter == "revenue":
            return self.get_revenue_trend(date_filter)
        elif type_filter == "conversation":
            return self.get_conversation_date_count(date_filter)
        elif type_filter == "ai_cost":
            return self.get_ai_cost_trend(date_filter)
        return self.get_user_date_count(date_filter)

    def _get_date_range(self, date_filter):
        now = timezone.now().date()
        if date_filter == '7d':
            return now - timezone.timedelta(days=7), now, 'day'
        elif date_filter == '6m':
            return now - timezone.timedelta(days=180), now, 'month'
        elif date_filter == '1y':
            return now - timezone.timedelta(days=365), now, 'month'
        elif date_filter == 'all':
            return None, now, 'month'
        # Default: 30d
        return now - timezone.timedelta(days=30), now, 'day'

    def get_user_date_count(self, date_filter):
        start_date, end_date, granularity = self._get_date_range(date_filter)
        qs = User.objects.all()
        if start_date:
            qs = qs.filter(created_time__range=(start_date, end_date))
        trunc = TruncDay if granularity == 'day' else TruncMonth
        key = 'day' if granularity == 'day' else 'month'
        return list(qs.annotate(**{key: trunc('created_time')}).values(key).annotate(count=Count('id')).order_by(key))

    def get_transaction_date_count(self, date_filter):
        start_date, end_date, granularity = self._get_date_range(date_filter)
        qs = Transaction.objects.all()
        if start_date:
            qs = qs.filter(created_time__range=(start_date, end_date))
        trunc = TruncDay if granularity == 'day' else TruncMonth
        key = 'day' if granularity == 'day' else 'month'
        return list(qs.annotate(**{key: trunc('created_time')}).values(key).annotate(count=Count('id')).order_by(key))

    def get_revenue_trend(self, date_filter):
        start_date, end_date, granularity = self._get_date_range(date_filter)
        qs = Transaction.objects.filter(status=PaymentStatuses.SUCCESS.value)
        if start_date:
            qs = qs.filter(created_time__range=(start_date, end_date))
        trunc = TruncDay if granularity == 'day' else TruncMonth
        key = 'day' if granularity == 'day' else 'month'
        return list(qs.annotate(**{key: trunc('created_time')}).values(key).annotate(
            count=Count('id'),
            total=Sum('amount')
        ).order_by(key))

    def get_conversation_date_count(self, date_filter):
        start_date, end_date, granularity = self._get_date_range(date_filter)
        qs = Conversation.objects.all()
        if start_date:
            qs = qs.filter(created_time__range=(start_date, end_date))
        trunc = TruncDay if granularity == 'day' else TruncMonth
        key = 'day' if granularity == 'day' else 'month'
        return list(qs.annotate(**{key: trunc('created_time')}).values(key).annotate(count=Count('id')).order_by(key))

    def get_ai_cost_trend(self, date_filter):
        start_date, end_date, granularity = self._get_date_range(date_filter)
        qs = Message.objects.filter(sender=SenderTypes.ASSISTANT.value)
        if start_date:
            qs = qs.filter(created_time__range=(start_date, end_date))
        trunc = TruncDay if granularity == 'day' else TruncMonth
        key = 'day' if granularity == 'day' else 'month'
        return list(qs.annotate(**{key: trunc('created_time')}).values(key).annotate(
            input_tokens=Sum('input_tokens'),
            output_tokens=Sum('output_tokens'),
            count=Count('id')
        ).order_by(key))


class DashboardTransactionSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'user', 'user_name', 'amount', 'status', 'currency',
            'transaction_type', 'payment_method', 'payment_details',
            'error_message', 'refund_amount', 'refund_date',
            'transaction_id', 'created_time', 'updated_time',
        ]

    def get_user_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name or ''} {obj.user.last_name or ''}".strip() or obj.user.username
        return None


class DashboardUserSerializer(serializers.ModelSerializer):
    subscription = serializers.SerializerMethodField()
    assistants = serializers.SerializerMethodField()
    integrations = serializers.SerializerMethodField()
    transactions = serializers.SerializerMethodField()
    conversation_and_message = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'last_name', 'phone_number', 'username',
            'email', 'user_role', 'is_active', 'subscription', 'assistants',
            'integrations', 'transactions', 'created_time', 'updated_time',
            'conversation_and_message',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_subscription(self, obj):
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

    def get_assistants(self, obj):
        return AssistantSerializer(obj.assistants.all(), many=True).data

    def get_integrations(self, obj):
        assistants = obj.assistants.all()
        integrations = []
        for assistant in assistants:
            integrations.extend(assistant.integrations.all())
        return IntegrationSerializer(integrations, many=True).data

    def get_transactions(self, obj):
        return DashboardTransactionSerializer(obj.transactions.all(), many=True).data

    def get_conversation_and_message(self, obj):
        conversations = Conversation.objects.filter(assistant__user=obj)
        conversation_count = conversations.count()
        assistant_msgs = Message.objects.filter(
            conversation__in=conversations, sender=SenderTypes.ASSISTANT.value
        )
        message_count = Message.objects.filter(conversation__in=conversations).count()
        message_input = sum([m.input_tokens for m in assistant_msgs])
        message_output = sum([m.output_tokens for m in assistant_msgs])
        return {
            "message_price": f"${(message_input/1000000 * 5) + (message_output/1000000 * 20):.2f}",
            "conversation_count": conversation_count,
            "message_count": message_count,
        }


class DashboardSubscriptionSerializer(serializers.ModelSerializer):
    pricing_package = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            'id', 'user', 'pricing_package', 'start_date', 'end_date',
            'status', 'remained_request_count', 'next_payment_date',
            'auto_renew', 'cancellation_reason', 'last_payment_date',
            'grace_period_days', 'created_time', 'updated_time',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_pricing_package(self, obj):
        if obj.pricing_package:
            return {
                "id": obj.pricing_package.id,
                "name": obj.pricing_package.name,
                "price": obj.pricing_package.price,
                "type": obj.pricing_package.type,
            }
        return None

    def get_user(self, obj):
        if obj.users.count() > 0:
            u = obj.users.first()
            return {
                "id": u.id,
                "username": u.username,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "email": u.email,
            }
        return None


class DashboardUserListSerializer(serializers.ModelSerializer):
    total_used_token_count = serializers.SerializerMethodField()
    subscription = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'phone_number',
            'email', 'user_role', 'is_active', 'total_used_token_count',
            'subscription', 'created_time', 'updated_time',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_total_used_token_count(self, obj):
        subscription = obj.subscription
        if subscription:
            return subscription.pricing_package.request_count - subscription.remained_request_count
        return 0

    def get_subscription(self, obj):
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


class DashboardPromptTemplateSerializer(serializers.ModelSerializer):
    assistants_count = serializers.SerializerMethodField()

    class Meta:
        model = PromptTemplate
        fields = [
            'id', 'name', 'description', 'content', 'is_default',
            'is_active', 'assistants_count', 'created_time', 'updated_time'
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_assistants_count(self, obj):
        return obj.assistants.count()


class DashboardLeadSerializer(serializers.ModelSerializer):
    assistant_name = serializers.CharField(source='assistant.name', read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id', 'full_name', 'phone_number', 'email', 'product',
            'metadata', 'status', 'platform', 'username', 'contacted',
            'assistant', 'assistant_name', 'created_time', 'updated_time',
        ]
        read_only_fields = ['created_time', 'updated_time']


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id', 'user', 'user_name', 'action', 'target_type',
            'target_id', 'target_repr', 'details', 'ip_address',
            'created_time',
        ]

    def get_user_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name or ''} {obj.user.last_name or ''}".strip() or obj.user.username
        return None


class ChangeRoleSerializer(serializers.Serializer):
    user_role = serializers.ChoiceField(choices=UserRoles.choices())


class RefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)
    reason = serializers.CharField(required=False, default='')
