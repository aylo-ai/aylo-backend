from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from django.utils.translation import gettext_lazy as _

from shared.addons.validations import raise_validation_error, check_number, phone_number_validation
from apps.user.models import User, PrivacyPolicy, UserAgreement


class SendCodeSerializer(serializers.Serializer): # noqa
    phone_number = serializers.CharField(required=True)

    def validate_phone_number(self, value):
        if not value:
            raise_validation_error(message=_("Telefon raqam kiritilmagan"))
        if not check_number(value):
            raise_validation_error(message=_("Notog'ri telefon raqam kiritilgan"))
        action = self.context.get('action')
        if action == 'register':
            if User.objects.filter(phone_number=value).exists():
                raise_validation_error(message=_("Bu telefon raqam allaqachon ro'yxatdan o'tgan"))
        elif action in ['forgot_password', 'login']:
            if not User.objects.filter(phone_number=value).exists():
                raise_validation_error(message=_("Telefon raqam topilmadi"))
        return value


class VerifyCodeSerializer(serializers.Serializer): # noqa
    phone_number = serializers.CharField(required=True)
    code = serializers.CharField(required=True)

    def validate(self, attrs):
        phone_number = attrs.get('phone_number', None)
        code = attrs.get('code', None)
        if not phone_number:
            raise_validation_error(message=_("Telefon raqam kiritilmagan"))
        if not code:
            raise_validation_error(message=_("Kod kiritilmagan"))
        return attrs

    def get_tokens(self): # noqa
        action = self.context.get('action', None)
        phone_number = self.validated_data.get('phone_number')
        print(f"action: {action}")
        if action == "login":
            user = User.objects.filter(phone_number=phone_number).first()
            print(f"user: {user}")
            return user.tokens()
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['tokens'] = self.get_tokens()
        return data


class RegisterUserSerializer(serializers.ModelSerializer):
    """Serializer for creating user objects."""

    tokens = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'password', 'phone_number', 'tokens')
        extra_kwargs = {
            'password': {'required': False},
            'phone_number': {'required': True},
            'first_name': {'required': True},
            'last_name': {'required': True},
            'username': {'required': False},
            'pricing_package': {'required': False},
        }

    def get_tokens(self, user): # noqa
        return user.tokens()

    def validate(self, attrs):
        first_name = attrs.get('first_name', None)
        last_name = attrs.get('last_name', None)
        # validate first name and last name to get only one word
        if len(first_name.split()) > 1:
            raise_validation_error(message=_("Ism faqat bir so'z bo'lishi kerak"))
        if len(last_name.split()) > 1:
            raise_validation_error(message=_("Familya faqat bir so'z bo'lishi kerak"))
        return attrs

    def validate_password(self, value): # noqa
        if len(value) < 8:
            raise_validation_error(message=_("Parol kamida 8 ta belgidan iborat bo'lishi kerak"))
        return value

    def validate_phone_number(self, value): # noqa
        # phone_number_validation(value)
        return value

    def create(self, validated_data):
        user = User(
            first_name=validated_data.get("first_name"),
            last_name=validated_data.get("last_name"),
            phone_number=validated_data.get("phone_number"),
            is_active=True,
        )
        user.save()
        return user


class LoginRefreshSerializer(serializers.Serializer):  # noqa
    refresh_token = serializers.CharField(required=True)

    def create(self, validated_data):
        refresh_token = validated_data.get("refresh_token")
        token = self.get_token_object(refresh_token)
        user = self.get_user_id_from_token(token)
        if not user:
            raise_validation_error(message=_("Refresh token noto'g'ri kiritilgan"))

        tokens = self.generate_tokens(user, token)
        return tokens

    @staticmethod
    def get_token_object(refresh_token):
        try:
            token_obj = RefreshToken(refresh_token)
            return token_obj
        except TokenError:
            raise raise_validation_error(message=_("Refresh token noto'g'ri kiritilgan"))

    @staticmethod
    def get_user_id_from_token(token_obj):
        user_id = token_obj.get('user_id', None)
        try:
            user = User.objects.get(id=user_id)
            return user
        except User.DoesNotExist:
            return None

    @staticmethod
    def generate_tokens(user, refresh_token):
        refresh = RefreshToken.for_user(user)
        refresh_token.blacklist()
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token)
        }


class UserSerializer(serializers.ModelSerializer):
    total_request_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'first_name',
            'last_name',
            'phone_number',
            'user_role',
            'pricing_package',
            'subscription_active',
            'next_payment_date',
            'used_request_count',
            "total_request_count"
        ]

    def get_total_request_count(self, obj): # noqa
        pricing_package = getattr(obj, 'pricing_package', None)
        if pricing_package:
            return pricing_package.request_count
        return 0


class UserShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id',
            'first_name',
            'last_name',
            'user_role',
        ]


class UpdateProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "username",
            "phone_number",
            "pricing_package",
        ]

        extra_kwargs = {
            "first_name": {"required": True},
            "last_name": {"required": True},
            "username": {"required": False},
            "pricing_package": {"required": False},
        }

    def validate(self, attrs):
        first_name = attrs.get('first_name', None)
        last_name = attrs.get('last_name', None)
        # validate first name and last name to get only one word
        if len(first_name.split()) > 1:
            raise_validation_error(message=_("Ism bir so'zdan iborat bo'lishi kerak"))
        if len(last_name.split()) > 1:
            raise_validation_error(message=_("Familya bir so'zdan iborat bo'lishi kerak"))
        return attrs

    def update(self, instance, validated_data):
        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.username = validated_data.get('username', instance.username)
        instance.save()
        return instance


class LogoutSerializer(serializers.Serializer): # noqa
    refresh_token = serializers.CharField(required=True)


class AddUserSerializer(serializers.Serializer):  # noqa
    first_name = serializers.CharField(required=True)
    last_name = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)
    user_role = serializers.CharField(required=True)

    def validate(self, attrs):
        phone_number = attrs.get('phone_number')
        if not check_number(phone_number):
            raise_validation_error(message=_("Notog'ri telefon raqam kiritilgan"))
        if User.objects.filter(phone_number=phone_number).exists():
            raise_validation_error(message=_("Bu telefon raqam allaqachon ro'yxatdan o'tgan"))

        return attrs

    def create(self, validated_data):
        context = self.context.get('request')
        company = context.user.company
        user = User.objects.create(
            first_name=validated_data.get('first_name'),
            last_name=validated_data.get('last_name'),
            phone_number=validated_data.get('phone_number'),
            user_role=validated_data.get('user_role'),
            company=company
        )
        return user


class DeleteCompanyUsersSerializer(serializers.Serializer):  # noqa
    user_ids = serializers.ListField(child=serializers.UUIDField(), required=True)

    def validate_user_ids(self, value):  # noqa
        if not value:
            raise_validation_error(message=_("Foydalanuvchilar tanlanmagan"))
        return value


class PrivacyPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = PrivacyPolicy
        fields = [
            'id',
            'title',
            'content',
            'is_active',
            'language',
        ]


class UserAgreementSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAgreement
        fields = [
            'id',
            'title',
            'content',
            'is_active',
            'language',
        ]