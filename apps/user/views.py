from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status, permissions
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils.translation import gettext_lazy as _

from config.settings import redis_connection
import user.serializers as serializers
from shared.addons.validations import error_response, success_response
from shared.addons.verification import send_code, verify_code_cache
from apps.user.models import User, PrivacyPolicy, UserAgreement
from shared.permissions import IsAdmin, IsSuperAdmin


class SendCodeView(generics.GenericAPIView):
    serializer_class = serializers.SendCodeSerializer
    throttle_classes = (AnonRateThrottle,)

    def post(self, request, *args, **kwargs):
        action = request.query_params.get("action")
        if not action:
            return error_response(message=_("Action kalit so'zi topilmadi"), code=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(data=request.data, context={"action": action})
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.data.get("phone_number")
        success, message = send_code(phone_number)
        if success:
            return success_response(data=serializer.data, message=message, code=status.HTTP_200_OK)
        return error_response(message=message, code=status.HTTP_400_BAD_REQUEST)


class VerifyCodeView(generics.GenericAPIView):
    serializer_class = serializers.VerifyCodeSerializer

    def post(self, request, *args, **kwargs):
        action = request.query_params.get("action")
        serializer = self.get_serializer(data=request.data, context={"action": action})
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.data.get("phone_number")
        code = serializer.data.get("code")
        print(f"phone_number: {phone_number}, code: {code}")
        # success, message = verify_code_cache(phone_number, code)
        success, message = True, _("Kod tasdiqlandi")
        if success:
            return success_response(data=serializer.data, message=message, code=status.HTTP_200_OK)
        return error_response(message=message, code=status.HTTP_400_BAD_REQUEST)


class UserRegisterView(generics.CreateAPIView):
    """Handles creating and listing Users."""
    queryset = User.objects.all()
    serializer_class = serializers.RegisterUserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        redis_connection.delete(serializer.data.get("phone_number") + "_verified")
        redis_connection.delete(serializer.data.get("phone_number"))
        return success_response(
            data=serializer.data,
            message=_("Foydalanuvchi muvaffaqiyatli yaratildi"),
            code=status.HTTP_201_CREATED,
        )


class LoginRefreshView(generics.GenericAPIView):
    serializer_class = serializers.LoginRefreshSerializer
    permission_classes = [permissions.AllowAny, ]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = serializer.save()
        return success_response(
            data=tokens,
            message=_("Login muvaffaqiyatli amalga oshirildi"),
            code=status.HTTP_200_OK
        )


class UserProfileGetView(generics.RetrieveAPIView):
    serializer_class = serializers.UserSerializer
    permission_classes = [permissions.IsAuthenticated, ]

    def get_object(self):
        return self.request.user


class UpdateProfileView(generics.UpdateAPIView):
    """Handles updating a user's profile."""
    queryset = User.objects.all()
    serializer_class = serializers.UpdateProfileSerializer
    permission_classes = [permissions.IsAuthenticated, ]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message=_("Foydalanuvchi ma'lumotlari muvaffaqiyatli yangilandi"),
            code=status.HTTP_200_OK
        )


class LogoutView(APIView):
    serializer_class = serializers.LogoutSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        try:
            refresh_token = self.request.data["refresh_token"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return success_response(
                message="You are logged out", code=status.HTTP_205_RESET_CONTENT
            )
        except TokenError:
            return error_response(
                code=status.HTTP_400_BAD_REQUEST, message=_("TokenEror - Noto'g'ri refresh token")
            )
        except Exception as e:
            return error_response(
                code=status.HTTP_400_BAD_REQUEST, message=_("Exception - Noto'g'ri refresh token")
            )


class PrivacyPolicyListCreateView(generics.ListCreateAPIView):
    queryset = PrivacyPolicy.objects.all()
    serializer_class = serializers.PrivacyPolicySerializer
    permission_classes = [IsAdmin, IsSuperAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["language", "is_active"]

    def get_permissions(self):
        if self.request.method == "GET":
            self.permission_classes = [permissions.AllowAny, ]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message=_("Privacy policy muvaffaqiyatli yaratildi"),
            code=status.HTTP_201_CREATED
        )


class PrivacyPolicyRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PrivacyPolicy.objects.all()
    serializer_class = serializers.PrivacyPolicySerializer
    permission_classes = [IsAdmin, IsSuperAdmin]

    def get_permissions(self):
        if self.request.method == "GET":
            self.permission_classes = [permissions.AllowAny, ]
        return super().get_permissions()

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message=_("Privacy policy muvaffaqiyatli yangilandi"),
            code=status.HTTP_200_OK
        )


class UserAgreementListCreateView(generics.ListCreateAPIView):
    queryset = UserAgreement.objects.all()
    serializer_class = serializers.UserAgreementSerializer
    permission_classes = [IsAdmin, IsSuperAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["language", "is_active"]

    def get_permissions(self):
        if self.request.method == "GET":
            self.permission_classes = [permissions.AllowAny, ]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message=_("User agreement muvaffaqiyatli yaratildi"),
            code=status.HTTP_201_CREATED
        )


class UserAgreementRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = UserAgreement.objects.all()
    serializer_class = serializers.UserAgreementSerializer
    permission_classes = [IsAdmin, IsSuperAdmin]

    def get_permissions(self):
        if self.request.method == "GET":
            self.permission_classes = [permissions.AllowAny, ]
        return super().get_permissions()

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message=_("User agreement muvaffaqiyatli yangilandi"),
            code=status.HTTP_200_OK
        )