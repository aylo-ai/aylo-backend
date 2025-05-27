from django.utils.translation import gettext as _
from django.utils import timezone

from shared.addons.validations import raise_validation_error
from shared.addons.enums import IntegrationTypes, SubscriptionStatuses

class SubscriptionValidationMixin:
    """
    Mixin to handle subscription validation across different serializers
    """
    def validate_subscription(self, subscription):
        """
        Validates user's subscription status
        Returns the subscription object if valid
        """
        if not subscription:
            raise_validation_error(message=_("Sizda obuna paketi yo'q. Iltimos, avval obuna paketini tanlang."))
        
        # Check if subscription is active
        if  subscription.status == SubscriptionStatuses.INACTIVE.value:
            raise_validation_error(message=_("Sizning obunangiz faol emas. Iltimos, obunangizni faollashtiring."))

        if subscription.next_payment_date < timezone.now().date() if subscription.next_payment_date else False:
            raise_validation_error(message=_("Sizning obunangiz muddati tugagan. Iltimos, obunangizni yangilang."))
        
        # Check if subscription has not expired
        # if subscription.end_date < timezone.now().date():
        #     raise_validation_error(message=_("Sizning obunangiz muddati tugagan. Iltimos, obunangizni yangilang."))
        
        return subscription
            

    def validate_assistant_count(self, subscription):
        assistants = subscription.assistants.count()
        if assistants >= 5:
            raise_validation_error(message=_("Sizning assistantlar soningiz tugagan. Iltimos, assistantlar sonini oshiring."))

    # def validate_intergation_count(self, user):
        # total_integrations = Integration.objects.filter(assistant=user.assistant).count()
        # if total_integrations >= 2:
        #     raise_validation_error(message=_("Sizning integratsiya soningiz tugagan. Iltimos, integratsiya sonini oshiring."))

    def validate_telegram_integration_count(self, subscription):
        telegram_integrations = subscription.integrations.filter(platform=IntegrationTypes.TELEGRAM.value).count()
        if telegram_integrations >= 1:
            raise_validation_error(message=_("Sizning telegram integratsiya soningiz tugagan. Iltimos, telegram integratsiya sonini oshiring."))

    def validate_instagram_integration_count(self, subscription):
        instagram_integrations = subscription.integrations.filter(platform=IntegrationTypes.INSTAGRAM.value).count()
        if instagram_integrations >= 1:
            raise_validation_error(message=_("Sizning instagram integratsiya soningiz tugagan. Iltimos, instagram integratsiya sonini oshiring."))

    def validate_assistant_file_upload_count(self, subscription):
        assistant_file_uploads = subscription.assistant_file_uploads.count()
        if assistant_file_uploads >= 40:
            raise_validation_error(message=_("Sizning assistant fayl yuklash soningiz tugagan. Iltimos, assistant fayl yuklash sonini oshiring."))
