from django.db import models

from apps.shared.models import BaseModel
from shared.addons.enums import PaymentMethods, PaymentStatuses, CurrencyType, TransactionTypes
from apps.user.models import User


class Feature(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'feature'

    def __str__(self):
        return self.name


class PricingPackage(BaseModel):
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    currency = models.CharField(
        max_length=50,
        null=True,
        choices=CurrencyType.choices(),
        default=CurrencyType.UZS.value,
    )
    description = models.TextField(null=True, blank=True)
    features = models.ManyToManyField(Feature, related_name='pricing_packages')

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
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    currency = models.CharField(
        max_length=50,
        null=True,
        choices=CurrencyType.choices(),
        default=CurrencyType.UZS.value,
    )

    class Meta:
        db_table = 'transaction'
        ordering = ["-created_time"]

    def __str__(self):
        return self.user.email


class Card(BaseModel):
    name = models.CharField(max_length=50, null=True, blank=True)
    card_token = models.TextField()
    card_number = models.CharField(max_length=16)
    expiry_date = models.CharField(max_length=10)
    is_verified = models.BooleanField(default=False)
    is_default = models.BooleanField(default=True)
    color = models.IntegerField(null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="cards")

    def save(self, *args, **kwargs):
        self.card_number = self.card_number[:4] + '*' * 8 + self.card_number[-4:]
        # undefault user's other cards
        if self.is_default:
            Card.objects.filter(user=self.user).exclude(id=self.id).update(is_default=False)
        super(Card, self).save(*args, **kwargs)

    def __str__(self):
        return f"Card({self.card_number}, {self.user.username})"

    class Meta:
        db_table = "Card"


class Balance(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="balance")
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
