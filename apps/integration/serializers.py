import requests

from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404

from .models import Integration, TelegramGroupIntegration, InstagramMedia, CommentTriggerWord, InstagramCommentResponse, CommentResponseButton, Step, Transition, Flow, InstagramUserState
from apps.assistant.models import Conversation, Assistant

from shared.addons.enums import IntegrationTypes, ConversationPlatforms, ConversationStatuses
from shared.addons.telegram import telegram_get_me, set_telegram_webhook, get_webhook_info, send_telegram_message
from shared.addons.utils import create_message
from shared.addons.validations import raise_validation_error, success_response
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
        assistant_id = self.context.get("assistant_id", None)
        try:
            assistant = Assistant.objects.filter(id=assistant_id).first()
            if not assistant.vector_id or not assistant.assistant_id:
                raise_validation_error(message=_("Assistant faol emas, zarur fayl yuklash"))
        except Assistant.DoesNotExist:
            raise_validation_error(message=_("Assistant topilmadi"))
        # Use the mixin's validation method
        self.validate_subscription(user.subscription)
        # validate integration count based on pricing package
        self.validate_intergation_count(user, assistant_id)

        if integration_type == IntegrationTypes.TELEGRAM.value and api_token:
            try:
                integration = Integration.objects.get(api_token=api_token, integration_type=IntegrationTypes.TELEGRAM.value)
                if integration:
                    success, code = telegram_get_me(api_token)
                    if not success or code == 401:
                        raise_validation_error(message=_("Telegram API token yaroqli emas"))
                    set_telegram_webhook(api_token, f"{base_url}/api/v1/integration/telegram/webhook/{api_token}/")
                    code = get_webhook_info(api_token)
                    if code == 400:
                        raise_validation_error(message=_("Telegram webhook topilmadi"))
            except Integration.DoesNotExist:
                pass
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
            "children"
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Try to fetch the latest data from Instagram; fall back to DB fields
        integration = None
        try:
            icr = instance.instagram_comment_responses.first()
            integration = getattr(icr, "integration", None)
        except Exception:
            integration = None

        if integration and getattr(integration, "api_token", None):
            url = (
                f"https://graph.instagram.com/v23.0/{instance.media_id}?fields="
                "id,caption,media_type,media_url,permalink,timestamp,username,children{media_type,media_url}"
            )
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {integration.api_token}",
            }
            try:
                resp = requests.get(url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    payload = resp.json() or {}
                    # Map payload to our model fields shape
                    data = {
                        "id": data.get("id"),
                        "media_id": payload.get("id") or instance.media_id,
                        "media_type": payload.get("media_type") or instance.media_type,
                        "media_url": payload.get("media_url") or instance.media_url,
                        "username": payload.get("username") or instance.username,
                        "timestamp": data.get("timestamp") or (instance.timestamp.isoformat() if instance.timestamp else None),
                        "caption": payload.get("caption") or instance.caption,
                        "comments_count": instance.comments_count,
                        "like_count": instance.like_count,
                        "children": instance.children,
                    }
                    return data
            except Exception:
                pass

        # Fallback to stored DB values, ensuring all fields are present
        data.setdefault("media_type", instance.media_type)
        data.setdefault("media_url", instance.media_url)
        data.setdefault("username", instance.username)
        data.setdefault("timestamp", instance.timestamp.isoformat() if instance.timestamp else None)
        data.setdefault("caption", instance.caption)
        data.setdefault("comments_count", instance.comments_count)
        data.setdefault("like_count", instance.like_count)
        data.setdefault("children", instance.children)
        return data
                

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
    
class CommentResponseButtonSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommentResponseButton
        fields = (
            "id",
            "text",
            "type",
            "url"
        )


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
        instagram_media_objs = []
        for media_data in instagram_media_list:
            media = InstagramMedia.objects.create(
                media_id=media_data.get('id'),
                media_type=media_data.get('media_type', None),
                media_url=media_data.get('media_url', None),
                username=media_data.get('username', None),
                timestamp=media_data.get('timestamp', None),
                caption=media_data.get('caption', None),
                comments_count=media_data.get('comments_count', None),
                like_count=media_data.get('like_count', None),
                children=media_data.get('children', None)
                )
            instagram_media_objs.append(media)
        
        # Add all media at once to prevent duplicates
        if instagram_media_objs:
            instance.instagram_media.add(*instagram_media_objs)

        instance.save()
        return instance
    
    def update(self, instance, validated_data):
        print(f"Instance: {instance}")
        trigger_words_list = validated_data.pop('trigger_words_list', [])
        instagram_media_list = validated_data.pop('instagram_media_list', [])
        instance = super().update(instance, validated_data)
        instance.trigger_words.clear()
        instance.instagram_media.all().delete()

        if trigger_words_list:
            trigger_word_objs = []
            for word in trigger_words_list:
                obj, _ = CommentTriggerWord.objects.get_or_create(trigger_word=word)
                trigger_word_objs.append(obj)
            instance.trigger_words.add(*trigger_word_objs)
        
        if instagram_media_list is not None:
            current_media_ids = set(instance.instagram_media.values_list('media_id', flat=True))
            new_media_ids = set(media.get('media_id') or media.get('id') for media in instagram_media_list)

            # Delete removed media
            for media in instance.instagram_media.filter(media_id__in=current_media_ids - new_media_ids):
                media.delete()

            # Update existing and add new
            for media_data in instagram_media_list:
                media_id = media_data.get('media_id')
                if media_id in current_media_ids:
                    # Update existing
                    media_obj = instance.instagram_media.get(media_id=media_id)
                    for field, value in media_data.items():
                        setattr(media_obj, field, value)
                    media_obj.save()
                else:
                    # Create new
                    obj = InstagramMedia.objects.create(
                        media_id=media_data.get('media_id') or media_data.get('id'),
                        media_type=media_data.get('media_type'),
                        media_url=media_data.get('media_url'),
                        username=media_data.get('username'),
                        caption=media_data.get('caption'),
                        timestamp=media_data.get('timestamp'),
                        comments_count=media_data.get('comments_count'),
                        like_count=media_data.get('like_count'),
                        children=media_data.get('children')
                    )
                    instance.instagram_media.add(obj)
        return instance
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        flow = instance.flows.first()
        
        if flow:
            last_step = flow.steps.filter(end_point=True).first()
            
            # Calculate conversion rate safely
            conversion_rate = 0
            if last_step and last_step.count > 0:
                conversion_rate = round((flow.total_count / last_step.count) * 100)
            
            data['flow'] = {
                "total_count": flow.total_count,
                "conversion": conversion_rate
            }
        else:
            data['flow'] = {
                "total_count": 0,
                "conversion": 0
            }
        
        return data
    
class TransitionListSerializer(serializers.ListSerializer):
    def create(self, validated_data):
        # bulk create transitions
        transitions = [Transition(**item) for item in validated_data]
        return Transition.objects.bulk_create(transitions)
    
class TransitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transition
        fields = ["id", "from_to", "to_step", "button_text",'action_subscription']
        list_serializer_class = TransitionListSerializer


class StepSerializer(serializers.ModelSerializer):
    extra_buttons = serializers.ListSerializer(
        child = serializers.DictField(
            child=serializers.CharField()
        ), write_only=True, required=False
    )
    extra_button = CommentResponseButtonSerializer(many=True, read_only=True)
    transitions = TransitionSerializer(many=True, source="transitions_from", read_only=True)

    class Meta:
        model = Step
        fields = ["id", "action", "extra_button", "start_point", "end_point", "count", "extra_buttons", "message_image","message_content","condition_type","transitions"]

    

class InstagramCommentResponseFlowSerializer(serializers.ModelSerializer):
    steps = StepSerializer(many=True, write_only=True)
    step = StepSerializer(many=True, read_only=True)

    class Meta:
        model = Flow
        fields = [
            "id",
            "title",
            "flow_type",
            "is_active",
            "comment_response",
            "step",
            "steps",
        ]
        extra_kwargs = {
            "comment_response": {"required": False},  # we attach manually in view
        }

    def create(self, validated_data):
        steps_data = validated_data.pop("steps", [])
        comment_response_id = self.context.get("comment_response_id")

        if not steps_data:
            raise serializers.ValidationError(
                {"steps": "Qadamlar yaratilmagan, avval yarating"}
            )

        # ensure comment_response exists
        comment_response = get_object_or_404(
            InstagramCommentResponse, id=comment_response_id
        )

        # create flow
        flow = Flow.objects.create(
            comment_response=comment_response, **validated_data
        )

        # create steps + buttons
        for step_data in steps_data:
            extra_buttons_data = step_data.pop("extra_buttons", [])
            step = Step.objects.create(flow=flow, **step_data)

            for btn_data in extra_buttons_data:
                btn = CommentResponseButton.objects.create(**btn_data)
                step.extra_button.add(btn)

        return flow
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["steps"] = StepSerializer(instance.steps.all(), many=True).data

        return data

class InstagramUserStateSerializer(serializers.ModelSerializer):
    current_step = StepSerializer(read_only=True)
    
    class Meta:
        model = InstagramUserState
        fields = [
            "id",
            "account_id", 
            "user_id", 
            "current_step", 
            "created_time", 
            "updated_time"
        ]
    