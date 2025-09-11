from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from django.utils.translation import gettext_lazy as _

from shared.addons.validations import raise_validation_error, check_number, check_email_phone_number
from apps.user.models import User, PrivacyPolicy, UserAgreement, Notification
from shared.addons.enums import AuthTypes, UserRoles

class SendCodeSerializer(serializers.Serializer): # noqa
    phone_number = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)

    def validate(self, attrs):
        phone_number = attrs.get('phone_number')
        email = attrs.get('email')
        
        if not phone_number and not email:
            raise_validation_error(message=_("Telefon raqam yoki email kiritilmagan"))
        
        if phone_number:
            if not check_number(phone_number):
                raise_validation_error(message=_("Notog'ri telefon raqam kiritilgan"))
        return attrs


class VerifyCodeSerializer(serializers.Serializer): # noqa
    phone_number = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    code = serializers.CharField(required=True)

    def validate(self, attrs):
        phone_number = attrs.get('phone_number')
        email = attrs.get('email')
        code = attrs.get('code')
        
        if not phone_number and not email:
            raise_validation_error(message=_("Telefon raqam yoki email kiritilmagan"))
        if not code:
            raise_validation_error(message=_("Kod kiritilmagan"))
        
        if email:
            user = User.objects.filter(email=email).first()
            if not user:
                user = User.objects.create(email=email, auth_type=AuthTypes.EMAIL.value)
        if phone_number:
            user = User.objects.filter(phone_number=phone_number).first()
            if not user:
                user = User.objects.create(phone_number=phone_number, auth_type=AuthTypes.PHONE.value)
        return attrs

    def get_tokens(self): # noqa
        phone_number = self.validated_data.get('phone_number', None)
        email = self.validated_data.get('email', None)
        if phone_number:
            user = User.objects.filter(phone_number=phone_number).first()
        elif email:
            user = User.objects.filter(email=email).first()
        if user:
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
        fields = ('id', 'first_name', 'last_name', 'password', 'phone_number', 'email', 'tokens')
        extra_kwargs = {
            'password': {'required': False},
            'phone_number': {'required': False},
            'email': {'required': False},
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
        phone_number = attrs.get('phone_number')
        email = attrs.get('email')
        
        if not phone_number and not email:
            raise_validation_error(message=_("Telefon raqam yoki email kiritilmagan"))
            
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
        if value and not check_number(value):
            raise_validation_error(message=_("Notog'ri telefon raqam kiritilgan"))
        return value

    def create(self, validated_data):
        user = User(
            first_name=validated_data.get("first_name"),
            last_name=validated_data.get("last_name"),
            phone_number=validated_data.get("phone_number"),
            email=validated_data.get("email"),
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
    total_used_token_count = serializers.SerializerMethodField()
    subscription = serializers.SerializerMethodField(method_name="get_subscription")
    integrations = serializers.SerializerMethodField(method_name="get_integrations")

    class Meta:
        model = User
        fields = [
            'id',
            'first_name',
            'last_name',
            'phone_number',
            'username',
            'email',
            'user_role',
            'total_used_token_count',
            'subscription',
            "integrations",
        ]
    
    def get_integrations(self, obj): # noqa
        integrations = obj.integrations.all()
        integrations_data = []
        for integration in integrations:
            integrations_data.append({
                "id": integration.id,
                "name": integration.name,
                "integration_type": integration.integration_type,
                "is_active": integration.is_active,
            })
        return integrations_data


    def get_total_used_token_count(self, obj): # noqa
        subscription = obj.subscription
        if subscription:
            return subscription.pricing_package.request_count - subscription.remained_request_count
        return 0
    
    def get_subscription(self, obj): # noqa
        subscription = obj.subscription
        if subscription:
            return {
                "id": subscription.id,
                "pricing_package": {
                    "id": subscription.pricing_package.id,
                    "name": subscription.pricing_package.name,
                    "type": subscription.pricing_package.type,
                    "price": subscription.pricing_package.price,
                    "request_count": subscription.pricing_package.request_count,
                    "duration_days": subscription.pricing_package.duration_days,
                    "discount_price": subscription.pricing_package.discount_price,
                    "currency": subscription.pricing_package.currency,
                },
                "start_date": subscription.start_date,
                "end_date": subscription.end_date,
                "status": subscription.status,
                "remained_request_count": subscription.remained_request_count,
                "next_payment_date": subscription.next_payment_date,
                "auto_renew": subscription.auto_renew,
                "cancellation_reason": subscription.cancellation_reason,
                "last_payment_date": subscription.last_payment_date,
                "grace_period_days": subscription.grace_period_days,
            }
        return None

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
        ]

        extra_kwargs = {
            "first_name": {"required": True},
            "last_name": {"required": True},
            "username": {"required": False},
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

class AddStaffSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email_or_phone_number'] = serializers.CharField(required=False)
        
    class Meta:
        model = User
        fields = [
            'id',
            'first_name', 
            'last_name',
        ]
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
        }
        
    def validate(self, attrs):
        first_name = attrs.get('first_name')
        last_name = attrs.get('last_name')
        email_or_phone_number = attrs.get('email_or_phone_number')

        if len(first_name.split()) > 1:
            raise_validation_error(message=_("Ism bir so'zdan iborat bo'lishi kerak"))
        if len(last_name.split()) > 1:
            raise_validation_error(message=_("Familya bir so'zdan iborat bo'lishi kerak"))


        auth_data = check_email_phone_number(email_or_phone_number)
        if auth_data == "phone":
            if User.objects.filter(phone_number=email_or_phone_number).exists():
                raise_validation_error(message=_("Bu telefon raqam allaqachon ro'yxatdan o'tgan"))
            else:
                data = {
                    "phone_number": email_or_phone_number,
                }
                    
        elif auth_data == "email":
            if User.objects.filter(email=email_or_phone_number).exists():
                raise_validation_error(message=_("Bu email allaqachon ro'yxatdan o'tgan"))
            else:
                data = {
                    "email": email_or_phone_number,
                }
        data["first_name"] = first_name
        data["last_name"] = last_name
        data["created_by"] = self.context['request'].user
        data["user_role"] = UserRoles.STAFF.value
        return data
    
    def create(self, validated_data):
        user = User.objects.create(**validated_data)
        user.save()
        return user
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["tokens"] = instance.tokens()
        return data
    
class NotificationSerializer(serializers.ModelSerializer):
    user = UserShortSerializer(read_only=True)
    class Meta:
        model = Notification
        fields = [
            'id',
            'title',
            'content',
            'is_read',
            'type',
            'user',
        ]
