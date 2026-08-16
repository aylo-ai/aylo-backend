from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from django.utils.translation import gettext_lazy as _

from apps.shared.addons.validations import raise_validation_error, check_number, check_email_phone_number
from apps.shared.addons.verification import check_verification_status, is_email_verified
from apps.user.models import User, PrivacyPolicy, UserAgreement, Notification
from apps.shared.addons.enums import AuthTypes, UserRoles

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
        return attrs

    def get_or_create_user(self):
        """Return the account for the verified identifier, creating it on first login.

        Called by the view only after the OTP has been confirmed, so an account is
        never created for an unverified — or brute-forced — identifier.
        """
        phone_number = self.validated_data.get('phone_number')
        email = self.validated_data.get('email')

        if phone_number:
            user, _created = User.objects.get_or_create(
                phone_number=phone_number,
                defaults={"auth_type": AuthTypes.PHONE.value},
            )
            return user

        user = User.objects.filter(email=email).order_by("created_time").first()
        if user is None:
            user = User.objects.create(email=email, auth_type=AuthTypes.EMAIL.value)
        return user


class RegisterUserSerializer(serializers.ModelSerializer):
    """Serializer for creating user objects.

    Registration is only allowed for an identifier that has already passed the
    OTP step (`/auth/verify-otp/`), so the endpoint cannot be used to mint
    accounts for phones or emails the caller does not control.
    """

    tokens = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'phone_number', 'email', 'tokens')
        extra_kwargs = {
            'phone_number': {'required': False},
            'email': {'required': False},
            'first_name': {'required': True},
            'last_name': {'required': True},
            'username': {'required': False},
            'pricing_package': {'required': False},
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
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

        # Reject duplicates with a clean 400 instead of a database IntegrityError.
        if phone_number and User.objects.filter(phone_number=phone_number).exists():
            raise_validation_error(message=_("Bu telefon raqam allaqachon ro'yxatdan o'tgan"))
        if email and User.objects.filter(email=email).exists():
            raise_validation_error(message=_("Bu email allaqachon ro'yxatdan o'tgan"))

        # The identifier must have been OTP-verified in the last few minutes.
        if phone_number:
            verified, message = check_verification_status(phone_number)
            if not verified:
                raise_validation_error(message=_("Telefon raqam tasdiqlanmagan"))
        if email and not is_email_verified(email):
            raise_validation_error(message=_("Email tasdiqlanmagan"))

        return attrs

    def validate_phone_number(self, value): # noqa
        if value and not check_number(value):
            raise_validation_error(message=_("Notog'ri telefon raqam kiritilgan"))
        return value

    def create(self, validated_data):
        phone_number = validated_data.get("phone_number")
        user = User(
            first_name=validated_data.get("first_name"),
            last_name=validated_data.get("last_name"),
            phone_number=phone_number,
            email=validated_data.get("email"),
            auth_type=AuthTypes.PHONE.value if phone_number else AuthTypes.EMAIL.value,
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
            # `RefreshToken(...)` verifies the signature and expiry *and* checks
            # the blacklist, so a rotated or logged-out token is rejected here.
            return RefreshToken(refresh_token)
        except TokenError:
            raise_validation_error(message=_("Refresh token noto'g'ri kiritilgan"))

    @staticmethod
    def get_user_id_from_token(token_obj):
        user_id = token_obj.get('user_id', None)
        # `is_active=True`: deactivating an account must stop it minting fresh
        # access tokens, not merely stop the ones it already holds.
        return User.objects.filter(id=user_id, is_active=True).first()

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
    
    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_integrations(self, obj): # noqa
        integrations = obj.integrations.filter(assistant__isnull=True)
        integrations_data = []
        for integration in integrations:
            integrations_data.append({
                "id": integration.id,
                "name": integration.name,
                "integration_type": integration.integration_type,
                "is_active": integration.is_active,
            })
        return integrations_data


    @extend_schema_field(OpenApiTypes.INT)
    def get_total_used_token_count(self, obj): # noqa
        subscription = obj.subscription
        # `pricing_package` is a SET_NULL FK, so a live subscription can have no
        # package (the package row was deleted). Without it there is no
        # allowance to subtract from, so "used" is unknowable — report 0 rather
        # than raising, which used to 500 this whole endpoint.
        if subscription and subscription.pricing_package:
            return subscription.pricing_package.request_count - subscription.remained_request_count
        return 0

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_subscription(self, obj): # noqa
        subscription = obj.subscription
        if subscription:
            package = subscription.pricing_package
            return {
                "id": subscription.id,
                # Null when the package was deleted out from under the
                # subscription; the key is always present so clients can read
                # it without guarding for its absence.
                "pricing_package": {
                    "id": package.id,
                    "name": package.name,
                    "type": package.type,
                    "price": package.price,
                    "request_count": package.request_count,
                    "duration_days": package.duration_days,
                    "discount_price": package.discount_price,
                    "currency": package.currency,
                } if package else None,
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
        # `update()` never wrote `phone_number` anyway, but leaving it writable
        # attached the model's uniqueness check to it: PATCHing an arbitrary
        # number answered "this phone number is already registered", which is a
        # free account-enumeration oracle. Changing the number has to go back
        # through OTP verification, so the field is output-only here.
        read_only_fields = ["id", "phone_number"]

        extra_kwargs = {
            "first_name": {"required": True},
            "last_name": {"required": True},
            "username": {"required": False},
        }

    def validate(self, attrs):
        first_name = attrs.get('first_name', None)
        last_name = attrs.get('last_name', None)
        # The view always updates partially, so either name may be absent —
        # `.split()` on the resulting None raised AttributeError (a 500) for an
        # empty body or any request that only changed the username.
        if first_name and len(first_name.split()) > 1:
            raise_validation_error(message=_("Ism bir so'zdan iborat bo'lishi kerak"))
        if last_name and len(last_name.split()) > 1:
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
        else:
            # Neither a valid email nor a valid phone number (or the field was
            # omitted entirely — it is declared `required=False`). Without this
            # branch `data` stays unbound and the next line raises
            # UnboundLocalError, turning a plain bad request into a 500.
            raise_validation_error(
                message=_("Email yoki telefon raqam noto'g'ri kiritilgan")
            )

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


class StaffListSerializer(serializers.ModelSerializer):
    email_or_phone = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email_or_phone', 'created_time']

    @extend_schema_field(OpenApiTypes.STR)
    def get_email_or_phone(self, obj):
        return obj.email or obj.phone_number or ''


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
            # Without this a notification row has nothing to timestamp itself
            # with, so clients can't show "2h ago" or order by recency.
            'created_time',
        ]
        # The update endpoint exists so a client can mark a notification read.
        # Everything else is written by the platform — a recipient rewriting the
        # title/content/type of a notice they were sent is not a feature.
        read_only_fields = ['id', 'title', 'content', 'type', 'created_time']
