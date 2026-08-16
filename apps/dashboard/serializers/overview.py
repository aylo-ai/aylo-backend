"""Dashboard overview, enhanced-stats and time-series statistics serializers."""
from django.db.models import Count, Sum
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone
from rest_framework import serializers

from apps.assistant.models import Assistant, Conversation, Message
from apps.payment.models import Subscription, Transaction
from apps.shared.addons.enums import (
    ConversationStatuses,
    MessageTypes,
    PaymentStatuses,
    SenderTypes,
    SubscriptionStatuses,
)
from apps.user.models import User


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
            status=SubscriptionStatuses.ACTIVE.value,
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
