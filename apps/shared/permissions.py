from django.contrib.auth import get_user_model

from rest_framework.request import Request
from rest_framework.permissions import IsAuthenticated

from shared.addons.enums import UserRoles

User = get_user_model()

DASHBOARD_ROLES = [
    UserRoles.SUPER_ADMIN.value,
    UserRoles.ADMIN.value,
    UserRoles.MANAGER.value,
    UserRoles.SUPPORT_AGENT.value,
    UserRoles.STAFF.value,
]

ADMIN_ROLES = [
    UserRoles.SUPER_ADMIN.value,
    UserRoles.ADMIN.value,
]

MANAGEMENT_ROLES = [
    UserRoles.SUPER_ADMIN.value,
    UserRoles.ADMIN.value,
    UserRoles.MANAGER.value,
]


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
            and request.user.user_role in ADMIN_ROLES
        )


class IsDashboardUser(IsAuthenticated):
    """Allows access to any user with a dashboard-eligible role."""
    message = "Sizda dashboard huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role in DASHBOARD_ROLES
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


class CanManageUsers(IsAuthenticated):
    """Super admin and admin can manage users."""
    message = "Sizda foydalanuvchilarni boshqarish huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role in ADMIN_ROLES
        )


class CanManageFinance(IsAuthenticated):
    """Super admin and admin can manage finance."""
    message = "Sizda moliya boshqarish huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role in ADMIN_ROLES
        )


class CanModerateConversations(IsAuthenticated):
    """Admin roles + support can moderate conversations."""
    message = "Sizda suhbatlarni boshqarish huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role in MANAGEMENT_ROLES + [UserRoles.SUPPORT_AGENT.value]
        )
