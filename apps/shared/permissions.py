from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from apps.shared.addons.enums import UserRoles

# Roles that may use the *internal* admin dashboard (`/api/v1/dashboard/…`):
# every user, assistant, conversation, transaction and subscription on the
# platform, across all tenants.
#
# `UserRoles.STAFF` must never appear here. A staff account is a *customer's*
# employee — any customer can mint one through `/api/v1/user/add-staff/`, which
# returns a ready-to-use token pair. While STAFF was a dashboard role, that
# endpoint was a self-service privilege escalation from "one tenant" to "read
# and write the whole platform".
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
    """Allows access to any user with a dashboard-eligible role."""
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
