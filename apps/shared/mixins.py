from django.utils.translation import gettext as _
from shared.addons.validations import raise_validation_error
from django.utils import timezone

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
            
            # Check if user has reached the request limit
            if subscription.used_request_count >= subscription.pricing_package.request_count:
                raise_validation_error(message=_("Sizning so'rovlar soningiz tugagan. Iltimos, obunangizni yangilang."))
            
            return subscription
            
        except (AttributeError, Exception) as e:
            raise_validation_error(message=_("Sizda obuna paketi yo'q. Iltimos, avval obuna paketini tanlang.")) 