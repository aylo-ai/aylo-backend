from django.contrib.auth import get_user_model

from rest_framework.request import Request
from rest_framework.permissions import IsAuthenticated

from shared.addons.enums import UserRoles

User = get_user_model()


class IsSuperAdmin(IsAuthenticated):
    message = "Sizda super admin huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role == UserRoles.SUPER_ADMIN.value
        )


class IsAdmin(IsAuthenticated):
    message = "Sizda admin huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role == UserRoles.ADMIN.value
        )


class IsManager(IsAuthenticated):
    message = "Sizda menejer huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role == UserRoles.MANAGER.value
        )


class IsSupportAgent(IsAuthenticated):
    message = "Sizda yordamchi huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role == UserRoles.SUPPORT_AGENT.value
        )


class IsCustomer(IsAuthenticated):
    message = "Sizda mijoz huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role == UserRoles.CUSTOMER.value
        )


class IsAdminOrCustomer(IsAuthenticated):
    message = "Sizda huquq yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role in (UserRoles.ADMIN.value, UserRoles.CUSTOMER.value)
        )
