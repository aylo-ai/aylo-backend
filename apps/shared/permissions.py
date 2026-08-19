from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from apps.shared.addons.enums import UserRoles

DASHBOARD_ROLES = [
    UserRoles.SUPER_ADMIN.value,
    UserRoles.ADMIN.value,
    UserRoles.MANAGER.value,
    UserRoles.SUPPORT_AGENT.value,
]

ADMIN_ROLES = [
    UserRoles.SUPER_ADMIN.value,
    UserRoles.ADMIN.value,
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
    message = "Sizda dashboard huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role in DASHBOARD_ROLES
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
    message = "Sizda foydalanuvchilarni boshqarish huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role in ADMIN_ROLES
        )


class CanManageFinance(IsAuthenticated):
    message = "Sizda moliya boshqarish huquqi yo'q!"

    def has_permission(self, request: Request, view):
        return bool(
            super().has_permission(request, view)
            and request.user.user_role in ADMIN_ROLES
        )
