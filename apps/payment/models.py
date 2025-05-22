from django.db import models
from django.core.validators import MinValueValidator
from apps.shared.models import BaseModel
from shared.addons.enums import PaymentMethods, PaymentStatuses, CurrencyType, TransactionTypes


class Feature(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    icon = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'feature'
        ordering = ['name']

    def __str__(self):
        return self.name


class PricingPackage(BaseModel):
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    discount_price = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(
        max_length=50,
        null=True,
        choices=CurrencyType.choices(),
        default=CurrencyType.UZS.value,
    )
    description = models.TextField(null=True, blank=True)
    request_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    duration_days = models.IntegerField(default=30, validators=[MinValueValidator(1)])
    features = models.ManyToManyField(Feature, related_name='pricing_packages', blank=True)
    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'pricing_package'
        ordering = ["-created_time"]

    def __str__(self):
        return self.name


class Transaction(BaseModel):
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    payment_method = models.CharField(max_length=100, null=True, blank=True,
                                      choices=PaymentMethods.choices())
    status = models.CharField(max_length=100, choices=PaymentStatuses.choices(),
                              default=PaymentStatuses.DRAFT.value)
    transaction_type = models.CharField(max_length=100, choices=TransactionTypes.choices(),
                                        null=True, blank=True)
    user = models.ForeignKey("user.User", on_delete=models.CASCADE, related_name='transactions')
    currency = models.CharField(
        max_length=50,
        null=True,
        choices=CurrencyType.choices(),
        default=CurrencyType.UZS.value,
    )
    transaction_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    payment_details = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    refund_amount = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    refund_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'transaction'
        ordering = ["-created_time"]

    def __str__(self):
        return f"{self.user.email} - {self.amount} - {self.status}"


class Card(BaseModel):
    name = models.CharField(max_length=50, null=True, blank=True)
    card_token = models.TextField()
    card_number = models.CharField(max_length=16)
    expiry_date = models.CharField(max_length=10)
    is_verified = models.BooleanField(default=False)
    is_default = models.BooleanField(default=True)
    color = models.IntegerField(null=True, blank=True)
    user = models.ForeignKey("user.User", on_delete=models.CASCADE, related_name="cards")

    def save(self, *args, **kwargs):
        self.card_number = self.card_number[:4] + '*' * 8 + self.card_number[-4:]
        # undefault user's other cards
        if self.is_default:
            Card.objects.filter(user=self.user).exclude(id=self.id).update(is_default=False)
        if not self.name:
            self.name = f"Card {self.card_number[-4:0]}"
        super(Card, self).save(*args, **kwargs)

    def __str__(self):
        return f"Card({self.card_number}, {self.user.username})"

    class Meta:
        db_table = "Card"


class Balance(BaseModel):
    user = models.OneToOneField("user.User", on_delete=models.CASCADE, related_name="balance")
    amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    currency = models.CharField(
        max_length=50,
        null=True,
        choices=CurrencyType.choices(),
        default=CurrencyType.UZS.value,
    )

    class Meta:
        db_table = 'balance'

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} - {self.amount}"

class Subscription(BaseModel):
    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="subscriptions"
    )
    pricing_package = models.ForeignKey(
        PricingPackage, on_delete=models.CASCADE, related_name="subscriptions"
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_subscription_active = models.BooleanField(default=True)
    next_payment_date = models.DateField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    used_request_count = models.IntegerField(default=0)
    auto_renew = models.BooleanField(default=True)
    cancellation_reason = models.TextField(null=True, blank=True)
    last_payment_date = models.DateField(null=True, blank=True)
    grace_period_days = models.IntegerField(default=0)  # for late payments
    subscription_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )  # for external payment systems

    class Meta:
        db_table = "subscription"
        ordering = ["-created_time"]

    def __str__(self):
        return f"{self.user.email} - {self.pricing_package.name} - {self.start_date} - {self.end_date}"