from rest_framework import serializers

from apps.assistant.models import Conversation
from apps.shared.addons.enums import SenderTypes, UserRoles
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