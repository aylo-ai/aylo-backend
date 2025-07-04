from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers
from django.db import transaction


from apps.payment.models import Feature, PricingPackage, Card, Transaction, Subscription, RetryPayment, Balance
from shared.addons.enums import TransactionTypes, PaymentStatuses, SubscriptionStatuses
from shared.addons.payment import check_payme_card_token, create_payme_receipt, commit_payme_receipt, \
    update_user_balance, send_create_card_request, send_verify_code_request, verify_payme_card_token, create_notification
from shared.addons.validations import raise_validation_error
from user.serializers import UserSerializer
from shared.addons.enums import PricingPackageType
from django.utils.translation import gettext_lazy as _


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
    class Meta:
        model = PricingPackage
        fields = [
            "id",
            "name",
            "price",
            "discount_price",
            "currency",
            "description",
            "features",
            "request_count",
            "duration_days",
            "is_popular",
        ]

    def validate(self, attrs):
        if attrs["price"] < 0:
            raise_validation_error(message=_("Narx manfiy bo'lishi mumkin emas."))
        if attrs["discount_price"] < attrs["price"]:
            raise_validation_error(message=_("Chegirma narxi narxdan kichik bo'lishi mumkin emas."))
        return attrs
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["features"] = FeatureSerializer(instance.features, many=True).data
        return data



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
    def validate(self, attrs):
        if attrs["expiry_date"] < timezone.now().date():
            raise_validation_error(message=_("Karta muddati o'tgan."))
        if attrs["card_number"] < 16:
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

    def validate_card_token(self, value):
        """Validate the card token with the Payme system."""
        response = check_payme_card_token(value)
        if not response:
            raise_validation_error(message=_("Karta tokeni noto'g'ri. Iltimos, tekshirib qaytadan yuboring."))

        card_data = response.json().get("result", {}).get("card", {})
        print(f"Card data: {card_data}")
        if not card_data.get("verify") or not card_data.get("recurrent"):
            raise_validation_error(message=_("Karta noto'g'ri. Iltimos, tekshirib qaytadan yuboring."))
        self.card_data = card_data  # noqa - Store card data for later use in create method
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        card_data = self.card_data

        # Prepare card data for saving
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
        print(f"validated_data: {validated_data}")
        create_response = send_create_card_request(
            validated_data.get("number"),
            validated_data.get("expire"),
        )
        print(f"create_response token: {create_response}")

        if "error" in create_response:
            raise_validation_error(
                message=_("Kartaning muddati 4 ta raqamdan kam bo'lishi mumkin emas."))

        token = create_response.get("result", {}).get("card", {}).get("token")

        verify_response = send_verify_code_request(token)
        if "error" in verify_response:
            raise_validation_error(
                message=_(verify_response.get("error").get("message"))
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
                message=_(verify_response.get("error").get("message"))
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
        """Validate card existence and retrieve its token."""
        card_id = attrs.get("card_id")
        subscription_id = attrs.get("subscription_id")

        try:
            subscription = Subscription.objects.get(id=subscription_id)
            if not subscription.pricing_package.is_active:
                raise_validation_error(message=_("Obuna paketi faol emas. Iltimos, tekshirib qaytadan yuboring."))
            # user = self.context.get("request").user
            # if user.subscription.id != subscription_id:
            #     raise_validation_error(message=lang("Sizda bunday obuna mavjud emas. Iltimos, tekshirib qaytadan yuboring."))
            price = subscription.pricing_package.price
            discount_price = subscription.pricing_package.discount_price
            attrs["amount"] = int(discount_price) if discount_price else int(price)
        except Subscription.DoesNotExist:
            raise_validation_error(message=_("Obuna topilmadi. Iltimos, tekshirib qaytadan yuboring."))

        try:
            card = Card.objects.get(id=card_id)
            if not card.is_verified:
                raise_validation_error(message=_("Karta tasdiqlanmagan. Iltimos, tekshirib qaytadan yuboring."))
            attrs["card_token"] = card.card_token
        except Card.DoesNotExist:
            raise_validation_error(message=_("Karta topilmadi. Iltimos, tekshirib qaytadan yuboring."))

        return attrs

    def create(self, validated_data):
        """Handle payment process."""
        user = self.context.get("request").user
        amount = validated_data.get("amount")
        card_token = validated_data.get("card_token")
        payment_method = validated_data.get("payment_method")
        is_withdrawal = self.context.get("is_withdrawal", False)

        try:
            with transaction.atomic():
                # Step 1: Create a Payme receipt
                success, message, receipt_id = create_payme_receipt(amount)
                success = True
                if not success:
                    raise_validation_error(message=_("To'lov chekini yaratishda tizim bilan bog'liq muammo yuz berdi: {}").format(message))
                transaction_type = TransactionTypes.WITHDRAW.value if is_withdrawal else TransactionTypes.DEPOSIT.value

                # Step 2: Log the transaction with DRAFT status
                transaction_obj = Transaction.objects.create(
                    user=user,
                    amount=amount,
                    payment_method=payment_method,
                    currency="UZS",
                    transaction_type=transaction_type,
                    status=PaymentStatuses.DRAFT.value,
                )

                # Step 3: Commit the Payme receipt
                success, message, receipt_id = commit_payme_receipt(card_token, receipt_id)
                if not success:
                    create_notification(user, message)
                    transaction_obj.error_message = message
                    transaction_obj.save()
                    raise_validation_error(message=_("To'lov tizimi bilan bog'liq muammo yuz berdi: {}").format(message))

                # Step 4: Update transaction status to COMMITTED
                transaction_obj.status = PaymentStatuses.SUCCESS.value
                transaction_obj.transaction_id = receipt_id
                transaction_obj.save()

                # Step 5: Update user balance
                if not is_withdrawal:
                    update_user_balance(user, amount)

                # Step 6: Update subscription
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
            # If anything fails, update transaction status and raise error
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
            raise_validation_error(message=_("To'lov jarayonida xatolik yuz berdi: {}").format(str(e)))


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
    user = UserSerializer(read_only=True)
    pricing_package = serializers.UUIDField(write_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "user",
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
        ]
        read_only_fields = [
            "user",
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

        # Check if user already has an active subscription
        try:
            existing_subscription = user.subscription
            if existing_subscription and existing_subscription.status == SubscriptionStatuses.ACTIVE.value:
                raise_validation_error(message=_("Sizda allaqachon faol obuna mavjud."))
        except (AttributeError, Subscription.DoesNotExist):
            pass

        # Validate pricing package
        try:
            pricing_package = PricingPackage.objects.get(id=pricing_package_id)
            if not pricing_package.is_active:
                raise_validation_error(message=_("Bu narx paketi hozirda faol emas."))
        except PricingPackage.DoesNotExist:
            raise_validation_error(message=_("Narx paketi topilmadi."))

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
        except PricingPackage.DoesNotExist:
            raise_validation_error(message=_("Narx paketi topilmadi."))

        try:
            card = Card.objects.get(id=card_id)
        except Card.DoesNotExist:
            raise_validation_error(message=_("Karta topilmadi."))
        
        attrs["card"] = card
        attrs["pricing_package"] = pricing_package
        return attrs
    
    def create(self, validated_data):
        user = self.context.get("request").user
        card = validated_data.get("card")
        pricing_package = validated_data.get("pricing_package")
        amount = int(pricing_package.discount_price)
        subscription = user.subscription
        with transaction.atomic():
             # 1. Create transaction with DRAFT status
            transaction1 = Transaction.objects.create(
                user=user,
                amount=amount,
                currency="UZS",
                transaction_type=TransactionTypes.WITHDRAW.value,
                status=PaymentStatuses.DRAFT.value,
            )

            # 2. Try to create payment receipt
            success, message, receipt_id = create_payme_receipt(amount)
            print(f"success: {success}")
            if not success:
                transaction1.status = PaymentStatuses.FAILED.value
                transaction1.error_message = message
                transaction1.save()
                subscription.status = SubscriptionStatuses.INACTIVE.value
                subscription.save()
                raise_validation_error(data=message)

            # 3. Try to commit payment
            success, message, receipt_id = commit_payme_receipt(card.card_token, receipt_id)
            print(f"success: {success}")
            if not success:
                create_notification(user, message)
                transaction1.status = PaymentStatuses.FAILED.value
                transaction1.error_message = message
                transaction1.save()
                subscription.status = SubscriptionStatuses.INACTIVE.value
                subscription.save()

                print(f"transaction1: {transaction1.status}")
                print(f"subscription: {subscription.status}")
                raise_validation_error(data=message)

            # 4. If successful, update transaction and subscription
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
            
            