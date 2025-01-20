from rest_framework import serializers

from apps.payment.models import Feature, PricingPackage, Card, Transaction
from shared.addons.enums import TransactionTypes, PaymentStatuses
from shared.addons.payment import check_payme_card_token, create_payme_receipt, commit_payme_receipt, \
    update_user_balance
from shared.addons.validations import raise_validation_error
from user.serializers import UserSerializer
from django.utils.translation import gettext as lang


class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = [
            "id",
            "name",
            "description",
        ]


class PricingPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingPackage
        fields = [
            "id",
            "name",
            "price",
            "description",
            "features",
            "request_count"
        ]

    def validate(self, attrs):
        if attrs["price"] < 0:
            raise_validation_error(message="Narx manfiy bo'lishi mumkin emas.")
        return attrs


class CardSerializer(serializers.ModelSerializer):
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
            raise_validation_error(message=lang("Karta tokeni noto'g'ri. Iltimos, tekshirib qaytadan yuboring."))

        card_data = response.json().get("result", {}).get("card", {})
        print(f"Card data: {card_data}")
        if not card_data.get("verify") or not card_data.get("recurrent"):
            raise_validation_error(message=lang("Karta noto'g'ri. Iltimos, tekshirib qaytadan yuboring."))
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
            is_recurrent=card_data.get("recurrent"),
            color=validated_data.get("color"),
            is_default=True,
        )
        return card


class PayWithCardSerializer(serializers.Serializer):  # noqa
    amount = serializers.IntegerField()
    card_id = serializers.UUIDField()

    def validate(self, attrs):
        """Validate card existence and retrieve its token."""
        card_id = attrs.get("card_id")
        try:
            card = Card.objects.get(id=card_id)
            if not card.is_verified:
                raise_validation_error(message=lang("Karta tasdiqlanmagan. Iltimos, tekshirib qaytadan yuboring."))
            attrs["card_token"] = card.card_token
        except Card.DoesNotExist:
            raise_validation_error(message=lang("Karta topilmadi. Iltimos, tekshirib qaytadan yuboring."))
        return attrs

    def create(self, validated_data):
        """Handle payment process."""
        user = self.context.get("request").user
        amount = validated_data.get("amount")
        card_token = validated_data.get("card_token")
        is_withdrawal = self.context.get("is_withdrawal", False)
        # Step 1: Create a Payme receipt
        success, message, receipt_id = create_payme_receipt(amount)
        if not success:
            raise_validation_error(message=lang("To'lov tizimi bilan bog'liq muammo yuz berdi: {message}"))
        transaction_type = TransactionTypes.WITHDRAW if is_withdrawal else TransactionTypes.DEPOSIT
        # Step 2: Log the transaction with DRAFT status
        transaction = Transaction.objects.create(
            user=user,
            amount=amount,
            currency="UZS",
            transaction_id=receipt_id,
            transaction_type=transaction_type,
            status=PaymentStatuses.DRAFT.value,
        )

        # Step 3: Commit the Payme receipt
        success, message, _ = commit_payme_receipt(card_token, receipt_id)
        if not success:
            raise_validation_error(message=lang("To'lov tizimi bilan bog'liq muammo yuz berdi: {message}"))

        # Step 4: Update transaction status to COMMITTED
        transaction.status = PaymentStatuses.SUCCESS.value
        transaction.save()

        # Step 5: Update user balance
        if not is_withdrawal:
            update_user_balance(user, amount)

        # Return the transaction for further processing if needed
        return {
            "transaction_id": transaction.transaction_id,
            "amount": transaction.amount,
            "status": transaction.status,
        }


class TransactionSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    transaction_id = serializers.CharField(required=False)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "user",
            "amount",
            "status",
            "currency",
            "created_time",
            "transaction_id",
            "transaction_type",
        ]