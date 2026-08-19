from datetime import timedelta

from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

import apps.payment.serializers as serializers
from apps.payment.models import (
    Card,
    Feature,
    PricingPackage,
    RetryPayment,
    Subscription,
    Transaction,
)
from apps.payment.services.billing import remove_payme_card
from apps.payment.services.notifications import notify_custom_package_request
from apps.shared.addons.enums import PricingPackageType, SubscriptionStatuses
from apps.shared.addons.validations import error_response, success_response
from apps.shared.permissions import IsAdmin


class FeatureListCreateView(generics.ListCreateAPIView):
    queryset = Feature.objects.filter(is_active=True)
    serializer_class = serializers.FeatureSerializer
    permission_classes = [IsAdmin]
    throttle_scope = "public_read"

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.AllowAny()]
        return [IsAdmin()]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message=_("Funksiya muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class FeatureRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Feature.objects.filter(is_active=True)
    serializer_class = serializers.FeatureSerializer
    permission_classes = [IsAdmin]
    throttle_scope = "public_read"

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.AllowAny()]
        return [IsAdmin()]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Funksiya muvaffaqiyatli ko'rsatildi"))

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Funksiya muvaffaqiyatli tahrirlandi"), data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Funksiya muvaffaqiyatli o'chirildi"), code=204)


class PricingPackageListCreateView(generics.ListCreateAPIView):
    queryset = PricingPackage.objects.filter(is_active=True).annotate(
        is_custom_tier=Case(
            When(type=PricingPackageType.CUSTOM.value, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by("is_custom_tier", "price", "created_time")
    serializer_class = serializers.PricingPackageSerializer
    permission_classes = [IsAdmin]
    throttle_scope = "public_read"

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsAdmin()]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message=_("Narx paketi muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class PricingPackageRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PricingPackage.objects.filter(is_active=True)
    serializer_class = serializers.PricingPackageSerializer
    permission_classes = [IsAdmin]
    throttle_scope = "public_read"

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsAdmin()]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Narx paketi muvaffaqiyatli olindi"))

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Narx paketi muvaffaqiyatli tahrirlandi"), data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Narx paketi muvaffaqiyatli o'chirildi"), code=204)


class CustomPackageRequestCreateView(generics.CreateAPIView):
    serializer_class = serializers.CustomPackageRequestSerializer
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "landing_lead"

    def create(self, request, *args, **kwargs):
        package = PricingPackage.objects.filter(
            id=self.kwargs.get("pk"), is_active=True,
        ).first()
        if package is None:
            return error_response(message=_("Narx paketi topilmadi."))
        if not package.is_custom:
            return error_response(
                message=_("Bu paketni to'g'ridan-to'g'ri xarid qilish mumkin.")
            )

        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "pricing_package": package},
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        notify_custom_package_request(instance)

        return success_response(
            message=_("Arizangiz qabul qilindi. Savdo bo'limi tez orada bog'lanadi."),
            data=serializer.data,
            code=201,
        )


class CardListView(generics.ListAPIView):
    serializer_class = serializers.CardSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Card.objects.none()
        return Card.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(
            data=serializer.data,
            message=_("Kartalar ro'yxati muvaffaqiyatli olindi"),
        )


class CardCreateWithPaymeView(generics.CreateAPIView):
    serializer_class = serializers.CardCreateSerializer
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_card"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return success_response(
            message=_("Karta muvaffaqiyatli saqlandi"),
            data=serializer.data,
            code=201,
        )


class SetDefaultCard(APIView):
    serializer_class = None
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        card_id = self.kwargs.get("pk", None)
        user = self.request.user
        if card_id is None:
            return error_response(message=_("Karta ID kiritilmagan"))

        default_card = Card.objects.filter(id=card_id, user=user).first()
        if default_card is None:
            return error_response(message=_("Karta topilmadi"))

        with transaction.atomic():
            default_card.is_default = True
            default_card.save()

        return success_response(
            message=_("{card} karta asosiy kartaga muvaffaqiyatli o'zgartirildi").format(
                card=default_card.card_number
            )
        )


class CardDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = serializers.CardSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Card.objects.none()
        return Card.objects.filter(user=self.request.user)

    def get_object(self):
        return self.get_queryset().filter(id=self.kwargs.get("pk")).first()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance is None:
            return error_response(message=_("Karta topilmadi"))
        serializer = self.get_serializer(instance)
        return success_response(
            data=serializer.data,
            message=_("Karta muvaffaqiyatli ko'rsatildi"),
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance is None:
            return error_response(message=_("Kalit topilmadi"))
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message=_("Karta muvaffaqiyatli tahrirlandi"),
        )

class PaymeGetVerifyCodeView(generics.CreateAPIView):
    serializer_class = serializers.PaymeGetVerifyCodeSerializer
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_card"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.save()
        return success_response(
            message=_("Verification code sent successfully"), data=data
        )

class PaymeVerifyCodeView(generics.CreateAPIView):
    serializer_class = serializers.PaymeVerifyCodeSerializer
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_card"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        is_card, card_data = serializer.save()
        return success_response(
            message=_("Verification code muvaffaqiyatli yuborildi"),
            data=serializers.CardSerializer(card_data).data if is_card else None,
        )

class CardRemoveView(generics.DestroyAPIView):
    serializer_class = serializers.CardSerializer
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_card"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Card.objects.none()
        return Card.objects.filter(user=self.request.user)

    def delete(self, request, *args, **kwargs):
        card = self.get_queryset().filter(id=self.kwargs["pk"]).first()
        if card is None:
            return error_response(message=_("Karta topilmadi"))
        card_token = card.card_token

        response = remove_payme_card(card_token)
        if not response:
            return error_response(
                message=_("To'lov tizimi bilan bog'lanishda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring"))
        card.delete()
        return success_response(
            message=_("Karta va uning ma'lumotlari muvaffaqiyatli o'chirildi"),
        )


class PayWithCard(generics.CreateAPIView):
    serializer_class = serializers.PayWithCardSerializer
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_charge"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.save()

        return success_response(
            message=_("Foydalanuvchi hisobi muvaffaqiyatli to'ldirildi"), data=data
        )


class ManualSubscriptionPaymentView(generics.CreateAPIView):
    serializer_class = serializers.PayWithCardSerializer
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_charge"

    def create(self, request, *args, **kwargs):
        user = request.user
        subscription = user.subscription
        if subscription is None:
            return error_response(message=_("Sizda obuna mavjud emas."))
        if not subscription.pricing_package:
            return error_response(message=_("Pullik obuna paketi yo'q. Iltimos, administrator bilan bog'laning."))

        serializer = self.get_serializer(
            data={"subscription_id": str(subscription.id), "card_id": request.data.get("card_id")},
            context={"request": request, "is_withdrawal": True}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        subscription.retry_count = 0
        subscription.status = SubscriptionStatuses.ACTIVE.value
        subscription.next_payment_date = now().date() + timedelta(days=30)
        subscription.save()

        return success_response(message=_("To'lov muvaffaqiyatli qabul qilindi, rahmat"))


class SubscriptionCreateView(generics.CreateAPIView):
    serializer_class = serializers.SubscriptionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Obuna muvaffaqiyatli yaratildi"), data=serializer.data)


class SubscriptionUpdateView(generics.CreateAPIView):
    serializer_class = serializers.SubscriptionUpdateSerializer
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_charge"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.save()
        return success_response(message=_("Obuna muvaffaqiyatli tahrirlandi"), data=data)

class SubscriptionCancellationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user

        cancellation_reason = request.data.get('cancellation_reason')
        if not cancellation_reason:
            return error_response(message=_("Bekor qilish sababi talab qilinadi"), code=400)

        subscription = user.subscription
        if subscription is None:
            return error_response(message=_("Sizda obuna mavjud emas."))
        subscription.status = SubscriptionStatuses.CANCELLED.value
        subscription.cancellation_reason = cancellation_reason
        subscription.save()

        return success_response(
            message=_("Obuna muvaffaqiyatli bekor qilindi"),
            data={"reason": subscription.cancellation_reason},
            code=200
        )

class TransactionListView(generics.ListAPIView):
    serializer_class = serializers.TransactionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        user = self.request.user
        if user.created_by:
            return Transaction.objects.filter(user__created_by=user)
        else:
            return Transaction.objects.filter(user=user)

class RetryPaymentListView(generics.ListAPIView):
    serializer_class = serializers.RetryPaymentSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        subscription_id = self.kwargs.get('pk')
        return RetryPayment.objects.filter(
            subscription_id=subscription_id,
            subscription__users=self.request.user,
        )

class SubscriptionUpdateAutoRenewView(generics.UpdateAPIView):
    serializer_class = serializers.SubscriptionUpdateAutoRenewSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return Subscription.objects.filter(users=self.request.user)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Obuna muvaffaqiyatli tahrirlandi"), data=serializer.data)
