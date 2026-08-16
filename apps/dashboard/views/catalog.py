"""Dashboard billing-catalog endpoints: features, pricing packages, balances, cards."""
from rest_framework import generics

from apps.dashboard.models import AuditLog
from apps.dashboard.serializers.catalog import (
    DashboardFeatureSerializer,
    DashboardPricingPackageDetailSerializer,
)
from apps.dashboard.views.base import get_client_ip
from apps.dashboard.views.mixins import (
    DashboardCreateMixin,
    DashboardDestroyMixin,
    DashboardListMixin,
    DashboardPartialUpdateMixin,
    DashboardRetrieveMixin,
)
from apps.payment.models import Balance, Card, Feature, PricingPackage
from apps.payment.serializers import (
    BalanceSerializer,
    CardSerializer,
    PricingPackageSerializer,
)
from apps.shared.addons.validations import success_response
from apps.shared.pagination import StandardResultsSetPagination
from apps.shared.permissions import IsAdmin, IsDashboardUser


class DashboardBalanceList(DashboardListMixin, generics.ListAPIView):
    queryset = Balance.objects.all()
    serializer_class = BalanceSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    list_message = "Balances retrieved successfully"


class DashboardCardList(DashboardListMixin, generics.ListAPIView):
    queryset = Card.objects.all()
    serializer_class = CardSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    list_message = "Cards retrieved successfully"


class DashboardFeatureList(DashboardListMixin, DashboardCreateMixin, generics.ListCreateAPIView):
    queryset = Feature.objects.all()
    serializer_class = DashboardFeatureSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    list_message = "Features retrieved successfully"
    create_message = "Feature created"


class DashboardFeatureDetail(
    DashboardRetrieveMixin,
    DashboardPartialUpdateMixin,
    DashboardDestroyMixin,
    generics.RetrieveUpdateDestroyAPIView,
):
    queryset = Feature.objects.all()
    serializer_class = DashboardFeatureSerializer
    permission_classes = [IsDashboardUser]
    retrieve_message = "Feature retrieved"
    update_message = "Feature updated"
    destroy_message = "Feature deleted"


class DashboardPricingPackageList(DashboardListMixin, DashboardCreateMixin, generics.ListCreateAPIView):
    queryset = PricingPackage.objects.prefetch_related('features').all()
    serializer_class = DashboardPricingPackageDetailSerializer
    permission_classes = [IsAdmin]
    pagination_class = StandardResultsSetPagination
    list_message = "Pricing packages retrieved successfully"
    create_message = "Pricing package created"


class DashboardPricingPackageDetail(
    DashboardRetrieveMixin,
    DashboardDestroyMixin,
    generics.RetrieveUpdateDestroyAPIView,
):
    queryset = PricingPackage.objects.prefetch_related('features').all()
    serializer_class = DashboardPricingPackageDetailSerializer
    permission_classes = [IsAdmin]
    retrieve_message = "Pricing package retrieved"
    destroy_message = "Pricing package deleted"

    def update(self, request, *args, **kwargs):
        # Writes go through the plain package serializer; the response is the
        # read serializer, which carries the subscriber-stats block.
        instance = self.get_object()
        serializer = PricingPackageSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.log(
            user=request.user, action='update', target_type='pricing_package',
            target_id=instance.id, target_repr=instance.name,
            details={'changes': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(data=DashboardPricingPackageDetailSerializer(instance).data, message="Pricing package updated", code=200)
