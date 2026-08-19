from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.dashboard.serializers.auth import (
    DashboardSendOtpLoginSerializer,
    DashboardVerifyOtpLoginSerializer,
)
from apps.shared.addons.validations import error_response, success_response
from apps.shared.addons.verification import send_code, verify_code_cache
from apps.user.models import User


class DashboardSendOtpLoginView(APIView):
    serializer_class = DashboardSendOtpLoginSerializer
    throttle_classes = (AnonRateThrottle,)

    def post(self, request, *args, **kwargs):
        from apps.shared.permissions import DASHBOARD_ROLES
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.data.get("phone_number")
        user = User.objects.filter(phone_number=phone_number).first()
        if user:
            if user.user_role in DASHBOARD_ROLES:
                success, message = send_code(phone_number)
            else:
                return error_response(message="Siz admin emassiz", code=400)
        else:
            return error_response(message="Bizda bunday foydalanuvchi topilmadi", code=400)

        if success:
            return success_response(data=serializer.data, message=message, code=200)
        return error_response(message=message, code=400)


class DashboardVerifyOtpLoginView(APIView):
    serializer_class = DashboardVerifyOtpLoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.data.get("phone_number")
        code = serializer.data.get("code")

        if phone_number:
            success, message = verify_code_cache(phone_number, code)
        else:
            return error_response(message="Telefon raqam yoki email kiritilmagan", code=400)
        if success:
            return success_response(data=serializer.data, message=message, code=200)
        return error_response(message=message, code=400)
