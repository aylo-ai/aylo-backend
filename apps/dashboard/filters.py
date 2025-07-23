from django_filters import rest_framework as filters

from apps.user.models import User
from apps.payment.models import SubscriptionStatuses, Subscription, Transaction
from shared.addons.enums import PaymentMethods, PaymentStatuses

class UserFilter(filters.FilterSet):
    date_range = filters.DateRangeFilter(field_name='created_time')

    class Meta:
        model = User
        fields = ['created_time']

class SubscriptionFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=SubscriptionStatuses.choices())

    class Meta:
        model = Subscription
        fields = ['status']

class TransactionFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=PaymentStatuses.choices())
    payment_method = filters.ChoiceFilter(choices=PaymentMethods.choices())

    class Meta:
        model = Transaction
        fields = ['status']
    

