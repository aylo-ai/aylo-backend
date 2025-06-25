from rest_framework import serializers

from apps.assistant.models import Conversation
from apps.shared.addons.enums import SenderTypes

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

    