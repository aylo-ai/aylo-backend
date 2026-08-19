import calendar
import logging
import re
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.payment.models import (
    Balance,
    Card,
    CustomPackageRequest,
    Feature,
    PricingPackage,
    RetryPayment,
    Subscription,
    Transaction,
)
from apps.payment.services.billing import (
    check_payme_card_token,
    commit_payme_receipt,
    create_notification,
    create_payme_receipt,
    payme_error_message,
    send_create_card_request,
    send_verify_code_request,
    update_user_balance,
    verify_payme_card_token,
)
from apps.shared.addons.enums import (
    PaymentStatuses,
    PricingPackageType,
    SubscriptionStatuses,
    TransactionTypes,
)
from apps.shared.addons.validations import raise_validation_error
from apps.user.serializers import UserSerializer

logger = logging.getLogger(__name__)


def parse_card_expiry(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 4:
        month, year = int(digits[:2]), 2000 + int(digits[2:])
    elif len(digits) == 6:
        month, year = int(digits[:2]), int(digits[2:])
    else:
        return None
    if not 1 <= month <= 12:
        return None
    return date(year, month, calendar.monthrange(year, month)[1])


class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = [
            "id",
            "name",
            "icon",
        ]

class BalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Balance
        fields = [
            "id",
            "user",
            "amount",
            "currency",
            "created_time",
            "updated_time",
        ]

class PricingPackageSerializer(serializers.ModelSerializer):
    is_custom = serializers.BooleanField(read_only=True)

    class Meta:
        model = PricingPackage
        fields = [
            "id",
            "name",
            "price",
            "discount_price",
            "is_custom",
            "currency",
            "description",
            "features",
            "request_count",
            "duration_days",
            "is_popular",
        ]

    def validate(self, attrs):
        price = attrs.get("price", getattr(self.instance, "price", None))
        discount_price = attrs.get(
            "discount_price", getattr(self.instance, "discount_price", None)
        )

        if price is not None and price < 0:
            raise_validation_error(message=_("Narx manfiy bo'lishi mumkin emas."))
        if discount_price is not None:
            if discount_price < 0:
                raise_validation_error(message=_("Chegirma narxi manfiy bo'lishi mumkin emas."))
            if price is not None and discount_price > price:
                raise_validation_error(
                    message=_("Chegirma narxi narxdan katta bo'lishi mumkin emas.")
                )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["features"] = FeatureSerializer(instance.features, many=True).data
        return data


class CustomPackageRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomPackageRequest
        fields = [
            "id",
            "company_name",
            "full_name",
            "phone_number",
            "email",
            "expected_conversations",
            "comment",
            "created_time",
        ]
        read_only_fields = ["id", "created_time"]

    def validate_phone_number(self, value):
        cleaned = re.sub(r"[\s\-()]", "", str(value or ""))
        if len(re.sub(r"\D", "", cleaned)) < 9:
            raise_validation_error(
                message=_("Telefon raqam kamida 9 ta raqamdan iborat bo'lishi kerak.")
            )
        return cleaned

    def validate_expected_conversations(self, value):
        if value is not None and value < 0:
            raise_validation_error(
                message=_("Suhbatlar soni manfiy bo'lishi mumkin emas.")
            )
        return value

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return CustomPackageRequest.objects.create(
            pricing_package=self.context.get("pricing_package"),
            user=user if user is not None and user.is_authenticated else None,
            **validated_data,
        )


class CardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Card
        fields = (
            "id",
            "name",
            "card_number",
            "expiry_date",
            "is_default",
            "color",
            "is_verified",
        )
        read_only_fields = (
            "card_number",
            "is_verified",
        )

    def validate(self, attrs):
        expiry_supplied = "expiry_date" in attrs
        expiry_date = attrs.get("expiry_date", getattr(self.instance, "expiry_date", None))
        card_number = attrs.get("card_number", getattr(self.instance, "card_number", None))

        if expiry_date is not None:
            expires_on = parse_card_expiry(expiry_date)
            if expires_on is None:
                if expiry_supplied:
                    raise_validation_error(
                        message=_("Karta amal qilish muddati noto'g'ri formatda (MM/YY).")
                    )
            elif expires_on < timezone.now().date():
                raise_validation_error(message=_("Karta muddati o'tgan."))

        if card_number is not None and len(card_number) < 16:
            raise_validation_error(message=_("Karta raqami 16 ta raqamdan kam bo'lishi mumkin emas."))
        return attrs


class CardCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Card
        fields = (
            "id",
            "name",
            "card_number",
            "expiry_date",
            "is_default",
            "card_token",
            "color",
            "is_verified",
        )
        extra_kwargs = {
            "card_token": {"write_only": True},
        }
        read_only_fields = (
            "card_number",
            "expiry_date",
            "is_verified",
        )

    def validate_card_token(self, value):
        user = self.context["request"].user
        if Card.objects.filter(card_token=value).exclude(user=user).exists():
            raise_validation_error(
                message=_("Bu karta boshqa foydalanuvchiga biriktirilgan.")
            )

        response = check_payme_card_token(value)
        if not response:
            raise_validation_error(message=_("Karta tokeni noto'g'ri. Iltimos, tekshirib qaytadan yuboring."))

        card_data = response.json().get("result", {}).get("card", {})
        if not card_data.get("verify") or not card_data.get("recurrent"):
            raise_validation_error(message=_("Karta noto'g'ri. Iltimos, tekshirib qaytadan yuboring."))
        self.card_data = card_data  # noqa - Store card data for later use in create method
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        card_data = self.card_data

        card = Card.objects.create(
            user=user,
            name=validated_data.get("name"),
            card_number=card_data.get("number"),
            expiry_date=card_data.get("expire"),
            card_token=card_data.get("token"),
            is_verified=card_data.get("verify"),
            color=validated_data.get("color"),
            is_default=True,
        )
        return card

class PaymeGetVerifyCodeSerializer(serializers.Serializer):  # noqa
    number = serializers.CharField()
    expire = serializers.CharField()

    def validate(self, attrs):
        number = attrs.get("number")
        expire = attrs.get("expire")
        if not number or not expire:
            raise_validation_error(
                message=_("Karta raqami va muddati talab qilinadi")
            )
        if len(number) != 16:
            raise_validation_error(message=_("Karta raqami 16 ta raqamdan kam bo'lishi mumkin emas."))
        if len(expire) != 4:
            raise_validation_error(message=_("Kartaning muddati 4 ta raqamdan kam bo'lishi mumkin emas."))
        return attrs

    def create(self, validated_data):
        create_response = send_create_card_request(
            validated_data.get("number"),
            validated_data.get("expire"),
        )

        if "error" in create_response:
            raise_validation_error(
                message=payme_error_message(
                    create_response, _("Kartani qo'shishda xatolik yuz berdi")
                )
            )

        token = create_response.get("result", {}).get("card", {}).get("token")

        verify_response = send_verify_code_request(token)
        if "error" in verify_response:
            raise_validation_error(
                message=payme_error_message(
                    verify_response, _("Tasdiqlash kodini yuborishda xatolik yuz berdi")
                )
            )
        return token


class PaymeVerifyCodeSerializer(serializers.Serializer):  # noqa
    token = serializers.CharField()
    code = serializers.CharField()

    def validate(self, attrs):
        token = attrs.get("token")
        code = attrs.get("code")
        if not token or not code:
            raise_validation_error(message=_("Token va kod talab qilinadi"))
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user

        verify_response = verify_payme_card_token(
            validated_data.get("token"), validated_data.get("code")
        )
        if "error" in verify_response:
            raise_validation_error(
                message=payme_error_message(
                    verify_response, _("Kartani tasdiqlashda xatolik yuz berdi")
                )
            )
        recurrent, verify = (
            verify_response.get("result").get("card").get("recurrent"),
            verify_response.get("result").get("card").get("verify"),
        )
        if not verify:
            raise_validation_error(message=_("Karta noto'g'ri. Iltimos, tekshirib qaytadan yuboring."))
        number, expire, token = (
            verify_response.get("result").get("card").get("number"),
            verify_response.get("result").get("card").get("expire"),
            verify_response.get("result").get("card").get("token"),
        )
        if recurrent:
            card = Card.objects.create(
                user=user,
                card_number=number,
                expiry_date=expire,
                card_token=token,
                is_verified=True
            )
            return True, card
        else:
            return True, None

class PayWithCardSerializer(serializers.Serializer):
    subscription_id = serializers.UUIDField()
    card_id = serializers.UUIDField()
    payment_method = serializers.CharField(required=False)

    def validate(self, attrs):
        user = self.context.get("request").user
        card_id = attrs.get("card_id")
        subscription_id = attrs.get("subscription_id")

        subscription = Subscription.objects.filter(id=subscription_id, users=user).first()
        if subscription is None:
            raise_validation_error(message=_("Obuna topilmadi. Iltimos, tekshirib qaytadan yuboring."))
        if not subscription.pricing_package or not subscription.pricing_package.is_active:
            raise_validation_error(message=_("Obuna paketi faol emas. Iltimos, tekshirib qaytadan yuboring."))

        price = subscription.pricing_package.price
        discount_price = subscription.pricing_package.discount_price
        attrs["amount"] = int(discount_price) if discount_price else int(price)

        card = Card.objects.filter(id=card_id, user=user).first()
        if card is None:
            raise_validation_error(message=_("Karta topilmadi. Iltimos, tekshirib qaytadan yuboring."))
        if not card.is_verified:
            raise_validation_error(message=_("Karta tasdiqlanmagan. Iltimos, tekshirib qaytadan yuboring."))
        attrs["card_token"] = card.card_token

        return attrs

    def create(self, validated_data):
        user = self.context.get("request").user
        amount = validated_data.get("amount")
        card_token = validated_data.get("card_token")
        payment_method = validated_data.get("payment_method")
        is_withdrawal = self.context.get("is_withdrawal", False)

        try:
            with transaction.atomic():
                success, message, receipt_id = create_payme_receipt(amount)
                if not success:
                    raise_validation_error(message=_("To'lov chekini yaratishda tizim bilan bog'liq muammo yuz berdi: {}").format(message))
                transaction_type = TransactionTypes.WITHDRAW.value if is_withdrawal else TransactionTypes.DEPOSIT.value

                transaction_obj = Transaction.objects.create(
                    user=user,
                    amount=amount,
                    payment_method=payment_method,
                    currency="UZS",
                    transaction_type=transaction_type,
                    status=PaymentStatuses.DRAFT.value,
                )

                success, message, receipt_id = commit_payme_receipt(card_token, receipt_id)
                if not success:
                    create_notification(user, message)
                    transaction_obj.error_message = message
                    transaction_obj.save()
                    raise_validation_error(message=_("To'lov tizimi bilan bog'liq muammo yuz berdi: {}").format(message))

                transaction_obj.status = PaymentStatuses.SUCCESS.value
                transaction_obj.transaction_id = receipt_id
                transaction_obj.save()

                if not is_withdrawal:
                    update_user_balance(user, amount)

                subscription = Subscription.objects.get(id=user.subscription.id)
                subscription.start_date = timezone.now().date()
                subscription.end_date = timezone.now().date() + timedelta(days=subscription.pricing_package.duration_days)
                subscription.status = SubscriptionStatuses.ACTIVE.value
                subscription.retry_count = 0
                subscription.auto_renew = True
                subscription.last_payment_date = timezone.now().date()
                subscription.save()

                return {
                    "amount": transaction_obj.amount,
                    "status": transaction_obj.status,
                    "subscription": {
                        "id": subscription.id,
                        "start_date": subscription.start_date,
                        "end_date": subscription.end_date,
                        "is_active": subscription.status
                    }
                }
        except Exception as e:
            try:
                transaction_obj.status = PaymentStatuses.FAILED.value
                transaction_obj.error_message = str(e)
                transaction_obj.save()
            except Exception:
                pass
            try:
                subscription.status = SubscriptionStatuses.INACTIVE.value
                subscription.save()
            except Exception:
                pass
            logger.exception("Card payment failed for user %s", user.id)
            raise_validation_error(message=_("To'lov jarayonida xatolik yuz berdi"))


class TransactionSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "user",
            "amount",
            "status",
            "currency",
            "created_time",
            "transaction_type",
            "payment_method",
            "payment_details",
            "error_message",
            "refund_amount",
            "refund_date",
        ]

class SubscriptionSerializer(serializers.ModelSerializer):
    pricing_package = serializers.UUIDField(write_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "pricing_package",
            "start_date",
            "end_date",
            "status",
            "next_payment_date",
            "retry_count",
            "remained_request_count",
            "auto_renew",
            "cancellation_reason",
            "last_payment_date",
            "grace_period_days",
            "created_time",
            "updated_time",
        ]
        read_only_fields = [
            "pricing_package",
            "start_date",
            "end_date",
            "status",
            "next_payment_date",
            "retry_count",
            "remained_request_count",
            "cancellation_reason",
            "last_payment_date",
            "grace_period_days",
        ]

    def validate(self, attrs):
        user = self.context.get("request").user
        pricing_package_id = attrs.get("pricing_package")

        try:
            existing_subscription = user.subscription
            if existing_subscription and existing_subscription.status == SubscriptionStatuses.ACTIVE.value:
                raise_validation_error(message=_("Sizda allaqachon faol obuna mavjud."))
        except (AttributeError, Subscription.DoesNotExist):
            pass

        try:
            pricing_package = PricingPackage.objects.get(id=pricing_package_id)
            if not pricing_package.is_active:
                raise_validation_error(message=_("Bu narx paketi hozirda faol emas."))
        except PricingPackage.DoesNotExist:
            raise_validation_error(message=_("Narx paketi topilmadi."))

        if pricing_package.is_custom:
            raise_validation_error(
                message=_(
                    "Bu paket kompaniyalar uchun individual shakllantiriladi. "
                    "Iltimos, ariza qoldiring — savdo bo'limi siz bilan bog'lanadi."
                )
            )

        attrs["pricing_package"] = pricing_package
        return attrs

    def create(self, validated_data):
        user = self.context.get("request").user
        pricing_package = validated_data.get("pricing_package")


        subscription = Subscription.objects.create(
            pricing_package=pricing_package,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=pricing_package.duration_days),
            retry_count=0,
            remained_request_count = pricing_package.request_count,
            )
        if pricing_package.price == 0:
            subscription.next_payment_date = None
            subscription.auto_renew = False
            subscription.status = SubscriptionStatuses.ACTIVE.value

        elif pricing_package.price > 0:
            subscription.next_payment_date = timezone.now().date() + timedelta(days=pricing_package.duration_days)
            subscription.auto_renew = True
            subscription.status = SubscriptionStatuses.INACTIVE.value
        user.subscription = subscription
        user.save()

        subscription.save()

        return subscription

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["pricing_package"] = (
            PricingPackageSerializer(instance.pricing_package).data
            if instance.pricing_package
            else None
        )
        return data


class SubscriptionUpdateAutoRenewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ["auto_renew"]

class RetryPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetryPayment
        fields = [
            "id",
            "subscription",
            "amount",
            "status",
            "retry_date",
            "error_message",
        ]

class SubscriptionUpdateSerializer(serializers.Serializer):
    pricing_package_id = serializers.UUIDField()
    card_id = serializers.UUIDField()

    def validate(self, attrs):
        pricing_package_id = attrs.get("pricing_package_id")
        card_id = attrs.get("card_id")

        user = self.context.get("request").user
        if not user.subscription:
            raise_validation_error(message=_("Sizda obuna mavjud emas."))

        if not pricing_package_id or not card_id:
            raise_validation_error(message=_("Narx paketi ID va karta ID talab qilinadi"))
        try:
            pricing_package = PricingPackage.objects.get(id=pricing_package_id)
            if not pricing_package.is_active:
                raise_validation_error(message=_("Narx paketi hozirda faol emas."))
            if pricing_package.type == PricingPackageType.FREE.value:
                raise_validation_error(message=_("Bu tekin paketni yangilash mumkin emas."))
            if pricing_package.is_custom:
                raise_validation_error(
                    message=_(
                        "Bu paket kompaniyalar uchun individual shakllantiriladi. "
                        "Iltimos, ariza qoldiring — savdo bo'limi siz bilan bog'lanadi."
                    )
                )
        except PricingPackage.DoesNotExist:
            raise_validation_error(message=_("Narx paketi topilmadi."))

        card = Card.objects.filter(id=card_id, user=user).first()
        if card is None:
            raise_validation_error(message=_("Karta topilmadi."))

        attrs["card"] = card
        attrs["pricing_package"] = pricing_package
        return attrs

    def create(self, validated_data):
        user = self.context.get("request").user
        card = validated_data.get("card")
        pricing_package = validated_data.get("pricing_package")
        discount_price = pricing_package.discount_price
        amount = int(discount_price) if discount_price else int(pricing_package.price)
        subscription = user.subscription
        with transaction.atomic():
            transaction1 = Transaction.objects.create(
                user=user,
                amount=amount,
                currency="UZS",
                transaction_type=TransactionTypes.WITHDRAW.value,
                status=PaymentStatuses.DRAFT.value,
            )

            success, message, receipt_id = create_payme_receipt(amount)
            if not success:
                transaction1.status = PaymentStatuses.FAILED.value
                transaction1.error_message = message
                transaction1.save()
                subscription.status = SubscriptionStatuses.INACTIVE.value
                subscription.save()
                raise_validation_error(data=message)

            success, message, receipt_id = commit_payme_receipt(card.card_token, receipt_id)
            if not success:
                create_notification(user, message)
                transaction1.status = PaymentStatuses.FAILED.value
                transaction1.error_message = message
                transaction1.save()
                subscription.status = SubscriptionStatuses.INACTIVE.value
                subscription.save()
                raise_validation_error(data=message)

            transaction1.status = PaymentStatuses.SUCCESS.value
            transaction1.transaction_id = receipt_id
            transaction1.save()

            update_user_balance(user, amount)

            subscription.next_payment_date = timezone.now().date() + timedelta(days=pricing_package.duration_days)
            subscription.end_date = timezone.now().date() + timedelta(days=pricing_package.duration_days)
            subscription.auto_renew = True
            subscription.retry_count = 0
            subscription.last_payment_date = timezone.now().date()
            subscription.grace_period_days = 0
            subscription.status = SubscriptionStatuses.ACTIVE.value
            subscription.pricing_package = pricing_package
            subscription.remained_request_count = pricing_package.request_count
            subscription.save()

            return {
                "amount": transaction1.amount,
                "status": transaction1.status,
                "subscription": {
                    "id": subscription.id,
                    "start_date": subscription.start_date,
                    "end_date": subscription.end_date,
                    "is_active": subscription.status
                }
            }
