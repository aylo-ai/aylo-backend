from django.utils.translation import gettext as _
from django.utils import timezone

from shared.addons.validations import raise_validation_error
from shared.addons.enums import IntegrationTypes

class SubscriptionValidationMixin:
    """
    Mixin to handle subscription validation across different serializers
    """
    def validate_subscription(self, user):
        """
        Validates user's subscription status
        Returns the subscription object if valid
        """
        try:
            subscription = user.subscription
            if not subscription:
                raise_validation_error(message=_("Sizda obuna paketi yo'q. Iltimos, avval obuna paketini tanlang."))
            
            # Check if subscription is active
            if not subscription.is_subscription_active:
                raise_validation_error(message=_("Sizning obunangiz faol emas. Iltimos, obunangizni faollashtiring."))

            if subscription.next_payment_date < timezone.now().date():
                raise_validation_error(message=_("Sizning obunangiz muddati tugagan. Iltimos, obunangizni yangilang."))
            
            # Check if subscription has not expired
            if subscription.end_date < timezone.now().date():
                raise_validation_error(message=_("Sizning obunangiz muddati tugagan. Iltimos, obunangizni yangilang."))
            
            return subscription
            
        except (AttributeError, Exception) as e:
            raise_validation_error(message=_("Sizda obuna paketi yo'q. Iltimos, avval obuna paketini tanlang.")) 

    def validate_assistant_count(self, user):
        assistants = user.assistants.count()
        if assistants >= 5:
            raise_validation_error(message=_("Sizning assistantlar soningiz tugagan. Iltimos, assistantlar sonini oshiring."))

    def validate_intergation_count(self, user):
        integrations = user.integrations.count()
        if integrations >= 5:
            raise_validation_error(message=_("Sizning integratsiya soningiz tugagan. Iltimos, integratsiya sonini oshiring."))

    def validate_telegram_integration_count(self, user):
        telegram_integrations = user.integrations.filter(platform=IntegrationTypes.TELEGRAM.value).count()
        if telegram_integrations >= 1:
            raise_validation_error(message=_("Sizning telegram integratsiya soningiz tugagan. Iltimos, telegram integratsiya sonini oshiring."))

    def validate_instagram_integration_count(self, user):
        instagram_integrations = user.integrations.filter(platform=IntegrationTypes.INSTAGRAM.value).count()
        if instagram_integrations >= 1:
            raise_validation_error(message=_("Sizning instagram integratsiya soningiz tugagan. Iltimos, instagram integratsiya sonini oshiring."))

    def validate_assistant_file_upload_count(self, user):
        assistant_file_uploads = user.assistant_file_uploads.count()
        if assistant_file_uploads >= 40:
            raise_validation_error(message=_("Sizning assistant fayl yuklash soningiz tugagan. Iltimos, assistant fayl yuklash sonini oshiring."))
