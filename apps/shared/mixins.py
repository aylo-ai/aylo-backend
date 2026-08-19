from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.shared.addons.enums import IntegrationTypes, SubscriptionStatuses
from apps.shared.addons.validations import raise_validation_error


class SubscriptionValidationMixin:
    def validate_subscription(self, subscription):
        if not subscription:
            raise_validation_error(message=_("Sizda obuna paketi yo'q. Iltimos, avval obuna paketini tanlang."))

        if subscription.status == SubscriptionStatuses.CANCELLED.value:
            raise_validation_error(message=_("Sizning obunangiz bekor qilingan. Iltimos, yangi obuna tanlang."))

        if subscription.status != SubscriptionStatuses.ACTIVE.value:
            if not subscription.last_payment_date:
                raise_validation_error(message=_("To'lov hali amalga oshirilmagan. Iltimos, to'lovni yakunlang."))
            raise_validation_error(message=_("Sizning obunangiz faol emas. Iltimos, obunangizni faollashtiring."))

        if subscription.remained_request_count <= 0:
            raise_validation_error(message=_("Sizning obunangiz tokeni tugagan. Iltimos, obunangizni yangilang."))

        if subscription.next_payment_date and subscription.next_payment_date < timezone.now().date():
            raise_validation_error(message=_("Sizning obunangiz muddati tugagan. Iltimos, obunangizni yangilang."))

        return subscription


    def validate_assistant_count(self, subscription):
        assistants = subscription.assistants.count()
        if assistants >= 5:
            raise_validation_error(message=_("Sizning assistantlar soningiz tugagan. Iltimos, assistantlar sonini oshiring."))

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
