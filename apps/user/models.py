from random import randint

from django.contrib.auth.models import AbstractUser
from django.db import models
from rest_framework_simplejwt.tokens import RefreshToken

from apps.payment.models import PricingPackage
from shared.addons.enums import UserRoles
from shared.models import BaseModel

from faker import Faker
fake = Faker()


class User(AbstractUser, BaseModel):
    first_name = models.CharField(max_length=45, null=True, blank=True)
    last_name = models.CharField(max_length=45, null=True, blank=True)
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    user_role = models.CharField(
        max_length=50,
        choices=UserRoles.choices(),
        default=UserRoles.CUSTOMER.value
    )
    pricing_package = models.ForeignKey(
        PricingPackage,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='users'
    )
    subscription_active = models.BooleanField(default=False)
    next_payment_date = models.DateField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    used_request_count = models.IntegerField(default=0)

    class Meta:
        db_table = "user"
        indexes = [
            models.Index(fields=['username']),
            models.Index(fields=['first_name']),
            models.Index(fields=['last_name']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['user_role']),
        ]

    def __str__(self):
        return self.username or self.phone_number

    def generate_username(self):
        if self.first_name and self.last_name and (self.phone_number or self.email):
            first_name_lower = self.first_name.lower()
            last_name_lower = self.last_name.lower()
            username = f"{first_name_lower}_{last_name_lower}_{self.phone_number[-4:]}"
            while User.objects.filter(username=username).exists():
                username = f"{first_name_lower}_{last_name_lower}{randint(1000, 9999)}"
        else:
            username = fake.user_name()
            while User.objects.filter(username=username).exists():
                username = fake.user_name()
        return username

    def save(self, *args, **kwargs):
        if not self.username:
            self.username = self.generate_username()
        super().save(*args, **kwargs)

    def tokens(self):
        refresh = RefreshToken.for_user(self)
        return {"access": str(refresh.access_token), "refresh": str(refresh)}


class PrivacyPolicy(BaseModel):
    title = models.CharField(max_length=255)
    content = models.TextField()
    is_active = models.BooleanField(default=True)
    language = models.CharField(max_length=10)

    def __str__(self):
        return self.title + " - " + self.language

    class Meta:
        db_table = "privacy_policy"
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['language']),
        ]


class UserAgreement(BaseModel):
    title = models.CharField(max_length=255)
    content = models.TextField()
    is_active = models.BooleanField(default=True)
    language = models.CharField(max_length=10)

    def __str__(self):
        return self.title + " - " + self.language

    class Meta:
        db_table = "user_agreement"
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['language']),
        ]