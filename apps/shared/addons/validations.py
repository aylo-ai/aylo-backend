import string
import re
from django.utils.translation import gettext_lazy as _

import phonenumbers
from rest_framework import status
from rest_framework.exceptions import APIException, _get_error_details
from rest_framework.response import Response

from shared.addons.verification import check_verification_status
from apps.user.models import User


class CustomValidationError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Invalid input.'
    default_code = 'invalid'

    def __init__(self, detail=None, code=None):
        if detail is None:
            detail = self.default_detail
        if code is None:
            code = self.default_code

        # For validation failures, we may collect many errors together,
        # so the details should always be coerced to a list if not already.
        if isinstance(detail, tuple):
            detail = dict(detail)
        elif not isinstance(detail, dict) and not isinstance(detail, list):
            detail = {detail}

        self.detail = _get_error_details(detail, code)


def success_response(data=None, message="Success", code=status.HTTP_200_OK):
    return Response({
        "success": True,
        "code": code,
        "message": message,
        "data": data
    }, status=code)


def error_response(data=None, message="Error", code=status.HTTP_400_BAD_REQUEST):
    return Response({
        "success": False,
        "code": code,
        "message": message,
        "data": data
    }, status=code)


def raise_validation_error(data=None, message="Error", code=400):
    raise CustomValidationError({
        "success": False,
        "code": int(code),
        "message": message,
        "data": data
    })


def check_number(phone_number):
    try:
        phone_number = phonenumbers.parse(phone_number, None)
        return phonenumbers.is_valid_number(phone_number)
    except phonenumbers.NumberParseException:
        return False
    
def check_email_phone_number(email_phone_number):
    """
    Check if the provided email or phone number is valid.
    """
    if re.match(r"^\+?[1-9]\d{1,14}$", email_phone_number):
        return "phone"
    elif re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email_phone_number):
        return "email"
    else:
        return {
            "message": "Invalid email or phone number format."
        }
    


def phone_number_validation(value):  # noqa
    if not value:
        raise_validation_error(message=_("Telefon raqamni kiritish majburiy"))
    if not check_number(value):
        raise_validation_error(message=_("Noto'g'ri telefon raqami kiritildi"))
    if User.objects.filter(phone_number=value).exists():
        raise_validation_error(message=_("Telefon raqam allaqachon ro'yxatdan o'tgan"))
    verification_status, message = check_verification_status(value)
    if not verification_status:
        raise_validation_error(message=message)


def is_password_valid(password):
    allowed_characters = string.ascii_letters + string.digits + string.punctuation
    if len(password) < 6 or any(ch not in allowed_characters for ch in password):
        return False, _("Parol kamida 6 ta belgidan iborat bo'lishi kerak")
    return True, ""
