from rest_framework import generics, permissions

from apps.payment.models import Feature, PricingPackage
from apps.payment.serializers import FeatureSerializer, PricingPackageSerializer
from shared.addons.validations import success_response
from shared.permissions import IsAdmin


class FeatureListCreateView(generics.ListCreateAPIView):
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message="Feature created successfully", data=serializer.data, code=201)


class FeatureRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Feature retrieved successfully")

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message="Feature updated successfully", data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message="Feature deleted successfully", code=204)


class PricingPackageListCreateView(generics.ListCreateAPIView):
    queryset = PricingPackage.objects.all()
    serializer_class = PricingPackageSerializer
    permission_classes = [IsAdmin]

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsAdmin()]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message="Pricing package created successfully", data=serializer.data, code=201)


class PricingPackageRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PricingPackage.objects.all()
    serializer_class = PricingPackageSerializer
    permission_classes = [IsAdmin]

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsAdmin()]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Pricing package retrieved successfully")

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message="Pricing package updated successfully", data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message="Pricing package deleted successfully", code=204)
