from datetime import timedelta

from django.utils.timezone import now
from rest_framework import generics, permissions
from rest_framework.views import APIView

from apps.payment.models import Feature, PricingPackage, Card, Subscription
import apps.payment.serializers as serializers
from shared.addons.payment import remove_payme_card
from shared.addons.validations import success_response, error_response
from shared.permissions import IsAdmin
from django.utils.translation import gettext as _
from shared.mixins import SubscriptionValidationMixin

class FeatureListCreateView(generics.ListCreateAPIView):
    queryset = Feature.objects.filter(is_active=True)
    serializer_class = serializers.FeatureSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message="Funksiya muvaffaqiyatli yaratildi", data=serializer.data, code=201)


class FeatureRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Feature.objects.filter(is_active=True)
    serializer_class = serializers.FeatureSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Funksiya muvaffaqiyatli ko'rsatildi")

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message="Funksiya muvaffaqiyatli tahrirlandi", data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message="Funksiya muvaffaqiyatli o'chirildi", code=204)


class PricingPackageListCreateView(generics.ListCreateAPIView):
    queryset = PricingPackage.objects.filter(is_active=True)
    serializer_class = serializers.PricingPackageSerializer
    permission_classes = [IsAdmin]

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsAdmin()]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message="Narx paketi muvaffaqiyatli yaratildi", data=serializer.data, code=201)


class PricingPackageRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PricingPackage.objects.filter(is_active=True)
    serializer_class = serializers.PricingPackageSerializer
    permission_classes = [IsAdmin]

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsAdmin()]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Narx paketi muvaffaqiyatli olindi")

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message="Narx paketi muvaffaqiyatli tahrirlandi", data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message="Narx paketi muvaffaqiyatli o'chirildi", code=204)


class CardListView(generics.ListAPIView):
    """API view to retrieve a list of cards based on user role"""

    serializer_class = serializers.CardSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return Card.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(
            data=serializer.data,
            message=_("Kartalar ro'yxati muvaffaqiyatli olindi"),
        )


class CardCreateWithPaymeView(generics.CreateAPIView):
    """API view to create a card"""

    serializer_class = serializers.CardCreateSerializer
    permission_classes = (permissions.IsAuthenticated,)
    queryset = Card.objects.all()

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

    def post(self, request):
        card_id = request.data.get("card_id", None)
        user = self.request.user
        if card_id is None:
            return error_response(message=_("Karta ID kiritilmagan"))
        user.cards.update(is_default=False)

        try:
            default_card = Card.objects.get(id=card_id)
            default_card.is_default = True
            default_card.save()
        except Card.DoesNotExist:
            return error_response(message=_("Karta topilmadi"))
        return success_response(
            message=_(
                f"{default_card.card_number[:4]}{'*' * 8}{default_card.card_number[-4:]} "
                f"karta asosiy kartaga muvaffaqiyatli o'zgartirildi"
            )
        )


class CardDetailView(generics.RetrieveUpdateAPIView):
    queryset = Card.objects.all()
    serializer_class = serializers.CardSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        card_id = self.kwargs.get("pk")
        try:
            card = Card.objects.get(id=card_id, user=self.request.user)
            return card
        except Card.DoesNotExist:
            return None

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


class CardRemoveView(generics.DestroyAPIView):
    queryset = Card.objects.all()
    serializer_class = serializers.CardSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def delete(self, request, *args, **kwargs):
        card_id = self.kwargs["pk"]
        try:
            card = Card.objects.get(id=card_id)
            card_token = card.card_token
        except Card.DoesNotExist:
            return error_response(message=_("Karta topilmadi"))

        response = remove_payme_card(card_token)
        if not response:
            return error_response(
                message=_(
                    "To'lov tizimi bilan bog'lanishda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring"
                )
            )
        # delete card object from Database table
        card.delete()
        return success_response(
            message=_("Karta va uning ma'lumotlari muvaffaqiyatli o'chirildi"),
        )


class PayWithCard(generics.CreateAPIView):
    serializer_class = serializers.PayWithCardSerializer
    permission_classes = (permissions.IsAuthenticated,)

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

    def create(self, request, *args, **kwargs):
        user = request.user
        if not user.subscription.pricing_package:
            return error_response(message=_("Pullik obuna paketi yo'q. Iltimos, administrator bilan bog'laning."))

        serializer = self.get_serializer(
            data={"amount": user.subscription.pricing_package.price, "card_id": request.data.get("card_id")},
            context={"request": request, "is_withdrawal": True}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Update user subscription details
        user.subscription.retry_count = 0
        user.subscription.is_subscription_active = True
        user.subscription.next_payment_date = now().date() + timedelta(days=30)
        user.subscription.save()

        return success_response(message=_("To'lov muvaffaqiyatli qabul qilindi, rahmat"))
    
class SubscriptionRetrieveView(generics.RetrieveAPIView):
    serializer_class = serializers.SubscriptionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        return Subscription.objects.get(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Obuna muvaffaqiyatli ko'rsatildi"), data=serializer.data)

class SubscriptionCreateView(generics.CreateAPIView):
    serializer_class = serializers.SubscriptionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Obuna muvaffaqiyatli yaratildi"), data=serializer.data)

class SubscriptionUpdateView(generics.UpdateAPIView):
    serializer_class = serializers.SubscriptionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        return Subscription.objects.get(user=self.request.user) 

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Obuna muvaffaqiyatli tahrirlandi"), data=serializer.data)

class SubscriptionCancellationView(APIView, SubscriptionValidationMixin):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, *args, **kwargs):
        user = request.user
        self.validate_subscription(user)

        # Get cancellation reason from request data
        cancellation_reason = request.data.get('cancellation_reason')
        if not cancellation_reason:
            return error_response(message=_("Cancellation reason is required"), code=400)

        # Update subscription status
        subscription = user.subscription
        subscription.is_subscription_active = False
        subscription.cancellation_reason = cancellation_reason
        subscription.save()
        
        return success_response(
            message=_("Subscription cancelled successfully"),
            data={"reason": subscription.cancellation_reason},
            code=200
        )
