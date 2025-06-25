from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from .models import Integration, TelegramGroupIntegration, InstagramMedia, CommentTriggerWord, InstagramCommentResponse
from apps.assistant.models import Conversation, Assistant

from shared.addons.enums import IntegrationTypes, ConversationPlatforms, ConversationStatuses
from shared.addons.telegram import telegram_get_me, set_telegram_webhook, get_webhook_info, send_telegram_message
from shared.addons.utils import create_message
from shared.addons.validations import raise_validation_error, success_response, error_response
from shared.mixins import SubscriptionValidationMixin


class IntegrationCreateSerializer(serializers.ModelSerializer, SubscriptionValidationMixin):
    class Meta:
        model = Integration
        fields = [
            "id",
            "assistant",
            "name",
            "description",
            "is_active",
            "api_token",
            "integration_type",
        ]
        extra_kwargs = {
            "assistant": {"required": False},
        }

    def validate(self, attrs):
        integration_type = attrs.get("integration_type")
        api_token = attrs.get("api_token", None)
        user = self.context.get("request").user
        base_url = self.context.get("base_url")
        assistant_id = self.context.get("assistant_id")
        try:
            assistant = Assistant.objects.get(id=assistant_id)
        except Assistant.DoesNotExist:
            raise_validation_error(message=_("Assistant topilmadi"))
        # Use the mixin's validation method
        self.validate_subscription(user.subscription)
        # validate integration count based on pricing package
        self.validate_intergation_count(user, assistant_id)

        if integration_type == IntegrationTypes.TELEGRAM.value and api_token:
            success, code = telegram_get_me(api_token)
            if not success or code == 401:
                raise_validation_error(message=_("Telegram API token yaroqli emas"))
            set_telegram_webhook(api_token, f"{base_url}/api/v1/integration/telegram/webhook/{api_token}/")
            code = get_webhook_info(api_token)
            if code == 400:
                raise_validation_error(message=_("Telegram webhook topilmadi"))
        elif integration_type == IntegrationTypes.INSTAGRAM.value:
            pass
        return attrs


class IntegrationSerializer(serializers.ModelSerializer, SubscriptionValidationMixin):
    class Meta:
        model = Integration
        fields = [
            "id",
            "assistant",
            "name",
            "description",
            "is_active",
            "integration_type",
            "api_token",
        ]
    
    def validate(self, attrs):
        assistant_id = self.context.get("assistant_id")
        print(f"Assistant ID {assistant_id}")
        try:
            assistant = Assistant.objects.get(id=assistant_id)
            if not assistant.ai_enabled:
                raise_validation_error(message=_("Assistant AI sizda yoqilmagan"))
            if not assistant.vector_id or not assistant.assistant_id:
                raise_validation_error(message=_("Assistant faol emas, zarur fayl yuklash"))
        except Assistant.DoesNotExist:
            raise_validation_error(message=_("Assistant topilmadi"))
        self.validate_subscription(assistant.user.subscription)
        return attrs


class TelegramGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramGroupIntegration
        fields = [
            "id",
            "integration",
            "group_id",
            "group_title",
            "lead_count",
            "created_time",
        ]


class SendUserMessageSerializer(serializers.Serializer, SubscriptionValidationMixin):  # noqa
    conversation_id = serializers.UUIDField()
    message = serializers.CharField()

    def validate(self, attrs):
        user = self.context.get("request").user
        # Use the mixin's validation method
        conversation_id = attrs.get("conversation_id")
        message = attrs.get("message")
        if not conversation_id or not message:
            raise_validation_error(message=_("Muloqot ID va xabar mavjud emas"))
        conversation = Conversation.objects.filter(id=conversation_id, assistant__user=user).first()
        self.validate_subscription(conversation.assistant.user.subscription)
        
        print(f"Conversation: {conversation}")
        if not conversation:
            raise_validation_error(message=_("Muloqot topilmadi"))
        if conversation.status != ConversationStatuses.ESCALATED.value:
            raise_validation_error(message=_("Muloqot xabar yuborish mumkin emas"))
        platform = conversation.platform
        attrs["platform"] = platform
        attrs["conversation"] = conversation
        if platform == ConversationPlatforms.TELEGRAM.value and \
                conversation.status == ConversationStatuses.ESCALATED.value:
            user_id = getattr(conversation, "telegram_user_id", None)
            bot_token = getattr(conversation, "token", None)
            if not user_id:
                raise_validation_error(message=_("Telegram foydalanuvchi ID topilmadi"))
            attrs["user_id"] = user_id
            if not bot_token:
                raise_validation_error(message=_("Telegram bot token topilmadi"))
            attrs["bot_token"] = bot_token

        return attrs

    def create(self, validated_data):
        platform = validated_data.get("platform")
        conversation = validated_data.get("conversation")
        if platform == ConversationPlatforms.TELEGRAM.value:
            user_id = validated_data.get("user_id")
            bot_token = validated_data.get("bot_token")
            message = validated_data.get("message")
            send_telegram_message(user_id, message, bot_token)
            create_message(conversation, "admin", message)

        if platform == ConversationPlatforms.WEBSITE.value:
            message = validated_data.get("message")
            create_message(conversation, "admin", message)

        return success_response(message=_("Xabar muvaffaqiyatli yuborildi"), code=200)


class InstagramMediaSerializer(serializers.ModelSerializer):
    children = serializers.JSONField(required=False)

    class Meta:
        model = InstagramMedia
        fields = [
            "id",
            "media_id",
            "media_type",
            "media_url",
            "username",
            "timestamp",
            "caption",
            "comments_count",
            "like_count",
            'children'
        ]


class CommentTriggerWordSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommentTriggerWord
        fields = [
            'id',
            'trigger_word'
        ]

    def validate_trigger_word(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError(_("Trigger word bo'sh bo'lishi mumkin emas"))
        
        return value.strip()


class InstagramCommentResponseSerializer(serializers.ModelSerializer):
    trigger_words = CommentTriggerWordSerializer(many=True, read_only=True)
    instagram_medias = InstagramMediaSerializer(source='instagram_media', many=True, read_only=True)

    trigger_words_list = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )
    instagram_media_list = serializers.ListField(
        child=serializers.JSONField(), write_only=True, required=False
    )

    class Meta:
        model = InstagramCommentResponse
        fields = [
            'id',
            'comment_message_template',
            'private_message_template',
            'trigger_words',
            'instagram_medias',
            'trigger_words_list',
            'instagram_media_list',
            'is_respond_to_all_comments'
        ]

    def validate(self, attrs):
        if not attrs.get('comment_message_template', '').strip() and not attrs.get('private_message_template', '').strip():
            raise serializers.ValidationError(_("Kamida bitta xabar shabloni kiritilishi kerak"))
        return attrs

    def create(self, validated_data):
        print(f"Validated data: {validated_data}")
        integration = self.context.get('integration')
        trigger_words_list = validated_data.pop('trigger_words_list', [])
        instagram_media_list = validated_data.pop('instagram_media_list', [])

        if len(trigger_words_list) == 0:
            validated_data['is_respond_to_all_comments'] = True
        else:
            validated_data['is_respond_to_all_comments'] = False

        instance = InstagramCommentResponse.objects.create(**validated_data, integration=integration)

        # Create or get trigger words
        for word in trigger_words_list:
            if word.strip():
                trigger_word, _ = CommentTriggerWord.objects.get_or_create(trigger_word=word.strip())
                instance.trigger_words.add(trigger_word)

        # Create or get Instagram media
        for media_data in instagram_media_list:
            media, _ = InstagramMedia.objects.get_or_create(
                                    media_id=media_data.get('id'), 
                                    media_type=media_data.get('media_type', None), 
                                    media_url=media_data.get('media_url', None), 
                                    username=media_data.get('username', None), 
                                    timestamp=media_data.get('timestamp', None), 
                                    caption=media_data.get('caption', None), 
                                    comments_count=media_data.get('comments_count', None), 
                                    like_count=media_data.get('like_count', None), 
                                    children=media_data.get('children', None))
            instance.instagram_media.add(media)

        instance.save()
        return instance
    
    def update(self, instance, validated_data):
        print(f"Validated data: {validated_data}")
        trigger_words_list = validated_data.pop('trigger_words_list', [])
        instagram_media_list = validated_data.pop('instagram_media_list', [])
        instance = super().update(instance, validated_data)
        instance.trigger_words.clear()
        instance.instagram_media.clear()

        if trigger_words_list:
            trigger_word_objs = []
            for word in trigger_words_list:
                obj, _ = CommentTriggerWord.objects.get_or_create(trigger_word=word)
                trigger_word_objs.append(obj)
            instance.trigger_words.add(*trigger_word_objs)
        if instagram_media_list:
            instagram_media_objs = []
            for media_data in instagram_media_list:
                print(f"Media data: {media_data}")
                obj, _ = InstagramMedia.objects.get_or_create(
                                    media_id=media_data.get('id'), 
                                    media_type=media_data.get('media_type', None), 
                                    media_url=media_data.get('media_url', None), 
                                    username=media_data.get('username', None), 
                                    timestamp=media_data.get('timestamp', None),
                                    caption=media_data.get('caption', None), 
                                    comments_count=media_data.get('comments_count', None), 
                                    like_count=media_data.get('like_count', None), 
                                    children=media_data.get('children', None))
                instagram_media_objs.append(obj)
            instance.instagram_media.add(*instagram_media_objs)
        return instance


