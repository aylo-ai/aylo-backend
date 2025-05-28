import base64
import json
import requests
from urllib.parse import urlencode
from django.shortcuts import redirect

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status, permissions
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils.translation import gettext_lazy as _

from config.settings import redis_connection, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
import user.serializers as serializers
from shared.addons.validations import error_response, success_response
from shared.addons.verification import send_code
from apps.user.models import User, PrivacyPolicy, UserAgreement
from shared.addons.verification import send_email_code, verify_email_code, verify_code_cache
from shared.permissions import IsAdmin, IsSuperAdmin, IsCustomer


class SendCodeView(generics.GenericAPIView):
    serializer_class = serializers.SendCodeSerializer
    throttle_classes = (AnonRateThrottle,)

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

    def post(self, request, *args, **kwargs):
        action = request.query_params.get("action")
        serializer = self.get_serializer(data=request.data, context={"action": action})
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.data.get("phone_number")
        email = serializer.data.get("email")
        code = serializer.data.get("code")
        
        if phone_number:
            success, message = verify_code_cache(phone_number, code)
        elif email:
            # success, message = verify_email_code(email, code)
            success, message = True, "Code verified successfully"
        else:
            return error_response(message=_("Telefon raqam yoki email kiritilmagan"), code=status.HTTP_400_BAD_REQUEST)
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
    
    
class GoogleLoginView(APIView):
    def get(self, request):
        google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent"
        }
        url = f"{google_auth_url}?{urlencode(params)}"
        print(f"google_auth_url: {url}")
        return redirect(url)
    
    
class GoogleAuthCallbackView(APIView):
    def get(self, request):
        try:
            code = request.GET.get("code")
            print(f"code: {code}")
            if not code:
                return error_response(message="Authorization code is missing", code=400)

            # Exchange code for tokens
            token_url = "https://oauth2.googleapis.com/token"
            data = {
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }
            token_response = requests.post(token_url, data=data)
            token_json = token_response.json()
            print(f"token_json: {token_json}")
            id_token = token_json.get("id_token")
            if not id_token:
                return error_response(message="ID token missing in response", code=400)
            try:
                payload = id_token.split('.')[1]
                padded = payload + '=' * (-len(payload) % 4)
                decoded = base64.urlsafe_b64decode(padded)
                user_info = json.loads(decoded)
            except Exception as decode_error:
                return error_response(message=f"Invalid ID token: {str(decode_error)}", code=400)
            print(f"user_info: {user_info}")
            sub = user_info.get("sub")
            print(f"sub: {sub}")
            if not sub:
                return error_response(message="Sub missing in user info", code=400)
            print("sub topildi")

            user = User.objects.filter(sub=sub).first()
            print(f"user: {user}")
            if not user:
                # create user
                user = User.objects.create(
                    sub=sub,
                    email=user_info.get("email", ""),
                    first_name=user_info.get("given_name", ""),
                    last_name=user_info.get("name", ""),
                )
                print(f"user created: {user}")
            tokens = user.tokens()
            return success_response(message="User authenticated successfully", data=tokens, code=status.HTTP_200_OK)
        except Exception as e:
            return error_response(message=str(e), code=400)

class AddStaffView(generics.CreateAPIView):
    queryset = User.objects.all()   
    serializer_class = serializers.AddStaffSerializer
    permission_classes = [IsCustomer]   

    def create(self, request, *args, **kwargs):
        if request.user.created_by is not None:
            return error_response(message="Uzur jigar sizda hodim yaratish huquqi yo'q", code=403)
        
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            message=_("Staff added successfully with access to your assistants"),
            data=serializer.data,
            code=status.HTTP_201_CREATED
        )