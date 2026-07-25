import logging
import secrets
import requests
from urllib.parse import urlencode
from django.shortcuts import redirect
from django.db.models import Q

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status, permissions
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils.translation import gettext_lazy as _

from config.settings import redis_connection, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
import user.serializers as serializers
from shared.addons.validations import error_response, success_response
from shared.addons.verification import send_code
from apps.user.models import User, PrivacyPolicy, UserAgreement, Notification
from shared.addons.verification import send_email_code, verify_email_code, verify_code_cache
from shared.permissions import IsAdmin, IsAdminOrCustomer
from shared.addons.enums import UserRoles, AuthTypes

logger = logging.getLogger(__name__)

class SendCodeView(generics.GenericAPIView):
    serializer_class = serializers.SendCodeSerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "otp_send"

    def post(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.data.get("phone_number")
        email = serializer.data.get("email")
        
        if phone_number:
            success, message = send_code(phone_number)
        elif email:
            success, message = send_email_code(email)
            # success, message = True, "Code sent successfully"
        else:
            return error_response(message=_("Telefon raqam yoki email kiritilmagan"), code=status.HTTP_400_BAD_REQUEST)
            
        if success:
            return success_response(data=serializer.data, message=message, code=status.HTTP_200_OK)
        return error_response(message=message, code=status.HTTP_400_BAD_REQUEST)


class VerifyCodeView(generics.GenericAPIView):
    serializer_class = serializers.VerifyCodeSerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "otp_verify"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data.get("phone_number")
        email = serializer.validated_data.get("email")
        code = serializer.validated_data.get("code")

        if phone_number:
            success, message = verify_code_cache(phone_number, code)
        elif email:
            success, message = verify_email_code(email, code)
        else:
            return error_response(message=_("Telefon raqam yoki email kiritilmagan"), code=status.HTTP_400_BAD_REQUEST)

        if not success:
            return error_response(message=message, code=status.HTTP_400_BAD_REQUEST)

        # Only now that the code is confirmed do we touch the database.
        user = serializer.get_or_create_user()
        data = {
            "phone_number": phone_number,
            "email": email,
            "tokens": user.tokens(),
        }
        return success_response(data=data, message=message, code=status.HTTP_200_OK)


class UserRegisterView(generics.CreateAPIView):
    """Handles creating and listing Users."""
    queryset = User.objects.all()
    serializer_class = serializers.RegisterUserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Clear verification cache for both phone and email
        phone_number = serializer.data.get("phone_number")
        email = serializer.data.get("email")
        
        if phone_number:
            redis_connection.delete(f"{phone_number}_verified")
            redis_connection.delete(phone_number)
        
        if email:
            redis_connection.delete(f"{email}_verified")
            redis_connection.delete(email)
            
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
                message=_("Siz muvaffaqiyatli chiqdingiz"), code=status.HTTP_205_RESET_CONTENT
            )
        except TokenError:
            return error_response(
                code=status.HTTP_400_BAD_REQUEST, message=_("TokenEror - Noto'g'ri refresh token")
            )
        except Exception:
            return error_response(
                code=status.HTTP_400_BAD_REQUEST, message=_("Exception - Noto'g'ri refresh token")
            )


class PrivacyPolicyListCreateView(generics.ListCreateAPIView):
    queryset = PrivacyPolicy.objects.all()
    serializer_class = serializers.PrivacyPolicySerializer
    permission_classes = [IsAdmin]
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
    permission_classes = [IsAdmin]

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
    permission_classes = [IsAdmin]
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
    permission_classes = [IsAdmin]

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
    
    
GOOGLE_STATE_TTL = 600  # seconds a login attempt's state token stays valid


class GoogleLoginView(APIView):
    def get(self, request):
        google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        # A one-time state token defends the callback against login-CSRF: only a
        # code that comes back with a state we issued is accepted.
        state = secrets.token_urlsafe(32)
        redis_connection.setex(f"google_oauth_state:{state}", GOOGLE_STATE_TTL, "1")
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        url = f"{google_auth_url}?{urlencode(params)}"
        return redirect(url)


class GoogleAuthCallbackView(APIView):
    def get(self, request):
        try:
            state = request.GET.get("state")
            if not state or not redis_connection.delete(f"google_oauth_state:{state}"):
                return error_response(message=_("Invalid or expired OAuth state"), code=400)

            code = request.GET.get("code")
            if not code:
                return error_response(message=_("Authorization code topilmadi"), code=400)

            # Exchange code for tokens
            token_url = "https://oauth2.googleapis.com/token"
            data = {
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }
            token_response = requests.post(token_url, data=data, timeout=30)
            raw_id_token = token_response.json().get("id_token")
            if not raw_id_token:
                return error_response(message=_("ID token topilmadi"), code=400)

            # Verify the signature, issuer, audience and expiry rather than trusting
            # a self-decoded payload.
            try:
                user_info = google_id_token.verify_oauth2_token(
                    raw_id_token, google_requests.Request(), GOOGLE_CLIENT_ID
                )
            except ValueError as verify_error:
                return error_response(
                    message=f"{_('Invalid ID token')}: {verify_error}", code=400
                )

            sub = user_info.get("sub")
            if not sub:
                return error_response(message=_("Sub topilmadi"), code=400)

            # Only trust the email claim for account matching/linking when Google
            # confirms it is verified — otherwise an attacker with an unverified
            # email equal to a victim's account email gets linked to the victim.
            email = user_info.get("email") or None
            email_verified = user_info.get("email_verified") is True
            user = User.objects.filter(Q(sub=sub) | Q(email=email)).first() if email and email_verified \
                else User.objects.filter(sub=sub).first()
            if not user:
                full_name = (user_info.get("name") or "").split(" ")
                if len(full_name) > 1:
                    first_name, last_name = full_name[0], full_name[1]
                else:
                    first_name = user_info.get("given_name", "")
                    last_name = user_info.get("family_name", "")
                user = User.objects.create(
                    sub=sub,
                    email=email if email_verified else None,
                    first_name=first_name,
                    last_name=last_name,
                    auth_type=AuthTypes.GOOGLE.value,
                )
            elif not user.sub:
                # Link an existing email account to this Google identity.
                user.sub = sub
                user.save(update_fields=["sub", "updated_time"])

            tokens = user.tokens()
            return success_response(message=_("Foydalanuvchi muvaffaqiyatli autentifikatsiya qilindi"), data=tokens, code=status.HTTP_200_OK)
        except Exception:
            logger.exception("Google OAuth callback failed")
            return error_response(message=_("Autentifikatsiya amalga oshmadi. Iltimos, qaytadan urinib ko'ring"), code=400)

class AddStaffView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = serializers.AddStaffSerializer
    permission_classes = [IsAdminOrCustomer]

    def create(self, request, *args, **kwargs):
        if request.user.created_by is not None:
            return error_response(message=_("Uzur jigar sizda hodim yaratish huquqi yo'q"), code=403)
        
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            message=_("Hodim muvaffaqiyatli yaratildi"),
            data=serializer.data,
            code=status.HTTP_201_CREATED
        )
        

class StaffListView(generics.ListAPIView):
    serializer_class = serializers.StaffListSerializer
    permission_classes = [IsAdminOrCustomer]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        return User.objects.filter(created_by=self.request.user, user_role=UserRoles.STAFF.value)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message=_("Xodimlar ro'yxati"), code=200)


class StaffDeleteView(generics.DestroyAPIView):
    serializer_class = serializers.StaffListSerializer
    permission_classes = [IsAdminOrCustomer]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        return User.objects.filter(created_by=self.request.user, user_role=UserRoles.STAFF.value)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return success_response(message=_("Hodim muvaffaqiyatli o'chirildi"), code=status.HTTP_200_OK)


class NotificationListView(generics.ListAPIView):
    queryset = Notification.objects.all()
    serializer_class = serializers.NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)
    

class NotificationUpdateView(generics.UpdateAPIView):
    serializer_class = serializers.NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Scope to the caller so one user cannot read or modify another's
        # notifications by guessing an id.
        return Notification.objects.filter(user=self.request.user)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Notification muvaffaqiyatli yangilandi"), data=serializer.data, code=status.HTTP_200_OK)
