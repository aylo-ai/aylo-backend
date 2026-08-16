from rest_framework.request import Request
from rest_framework.permissions import IsAuthenticated

from apps.shared.addons.enums import UserRoles

<<<<<<< HEAD
User = get_user_model()

# Roles that may see the internal admin console at all.
#
# `UserRoles.STAFF` is deliberately NOT here. The only thing in the codebase
# that ever mints a `staff` account is `AddStaffView`
# (`POST /api/v1/user/add-staff/`) — a *customer-facing* "add my employee"
# feature that any customer may call and that returns the new account's JWT in
# its own 201 body. While `staff` was a dashboard role, that made customer →
# platform-admin privilege escalation a two-request operation: create an
# employee, then use the token it hands you against `IsDashboardUser` routes
# such as `/dashboard/users/`, `/dashboard/cards/`, `/dashboard/transactions/`
# and `/dashboard/search/`, none of which scope their querysets by tenant.
# Internal console roles are super_admin / admin / manager / support_agent.
=======
# Roles that may use the *internal* admin dashboard (`/api/v1/dashboard/…`):
# every user, assistant, conversation, transaction and subscription on the
# platform, across all tenants.
#
# `UserRoles.STAFF` must never appear here. A staff account is a *customer's*
# employee — any customer can mint one through `/api/v1/user/add-staff/`, which
# returns a ready-to-use token pair. While STAFF was a dashboard role, that
# endpoint was a self-service privilege escalation from "one tenant" to "read
# and write the whole platform".
>>>>>>> 473f4c3bed1052b8f0214fd63847c983cff0e728
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
