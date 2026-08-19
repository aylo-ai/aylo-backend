from rest_framework import serializers

from apps.payment.models import Transaction


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


class RefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)
    reason = serializers.CharField(required=False, default='')


class TransactionBulkActionSerializer(serializers.Serializer):
    ACTIONS = ('refund',)

    action = serializers.ChoiceField(choices=ACTIONS)
    ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
