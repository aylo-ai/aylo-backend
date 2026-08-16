"""Dashboard user administration endpoints."""
import csv

from django.db.models import Q
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.views import APIView

from apps.dashboard.filters import UserFilter
from apps.dashboard.models import AuditLog
from apps.dashboard.serializers.users import (
    ChangeRoleSerializer,
    DashboardUserListSerializer,
    DashboardUserSerializer,
    UserBulkActionSerializer,
)
from apps.dashboard.views.base import get_client_ip
from apps.dashboard.views.mixins import DashboardRetrieveMixin
from apps.shared.addons.enums import UserRoles
from apps.shared.addons.validations import error_response, success_response
from apps.shared.pagination import StandardResultsSetPagination
from apps.shared.permissions import CanManageUsers, IsAdmin, IsDashboardUser
from apps.user.models import User


class DashboardUserList(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = DashboardUserListSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = UserFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["username", "email", "phone_number", 'first_name', 'last_name']
    ordering_fields = ['created_time', 'first_name', 'last_name', 'email', 'user_role']
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = {
                "data": serializer.data,
                "total_users": queryset.count(),
                "active_users": queryset.filter(is_active=True).count(),
                "admin_users": queryset.filter(user_role__in=[UserRoles.ADMIN.value, UserRoles.SUPER_ADMIN.value]).count(),
                "customer_users": queryset.filter(user_role=UserRoles.CUSTOMER.value).count(),
            }
            return self.get_paginated_response(response)
        serializer = self.get_serializer(queryset, many=True)
        response = {
            "data": serializer.data,
            "total_users": queryset.count(),
            "active_users": queryset.filter(is_active=True).count(),
            "admin_users": queryset.filter(user_role__in=[UserRoles.ADMIN.value, UserRoles.SUPER_ADMIN.value]).count(),
            "customer_users": queryset.filter(user_role=UserRoles.CUSTOMER.value).count(),
        }
        return success_response(data=response, message="Users retrieved successfully", code=200)


class DashboardUserDetail(DashboardRetrieveMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    serializer_class = DashboardUserSerializer
    permission_classes = [IsDashboardUser]
    retrieve_message = "User retrieved successfully"

    def get_permissions(self):
        # PUT/PATCH can write `user_role` and `is_active` — the same fields the
        # dedicated CanManageUsers-gated toggle-active/change-role endpoints
        # protect — and DELETE removes the account outright, so any
        # IsDashboardUser role (support_agent, staff, manager) must not reach
        # them through this generic view.
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [CanManageUsers()]
        return super().get_permissions()

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return User.objects.filter(id=pk)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.log(
            user=request.user, action='update', target_type='user',
            target_id=instance.id,
            target_repr=str(instance),
            details={'changes': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(data=serializer.data, message="User updated successfully", code=200)

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        AuditLog.log(
            user=request.user, action='delete', target_type='user',
            target_id=self.kwargs.get("pk"),
            target_repr=str(user),
            ip_address=get_client_ip(request),
        )
        user.delete()
        return success_response(message="User deleted successfully", code=200)


class DashboardUserToggleActive(APIView):
    permission_classes = [CanManageUsers]

    def post(self, request, pk):
        try:
            user = User.objects.get(id=pk)
        except User.DoesNotExist:
            return error_response(message="User not found", code=404)

        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])

        AuditLog.log(
            user=request.user,
            action='block' if not user.is_active else 'unblock',
            target_type='user',
            target_id=pk,
            target_repr=str(user),
            details={'is_active': user.is_active},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'is_active': user.is_active},
            message=f"User {'activated' if user.is_active else 'deactivated'} successfully",
            code=200
        )


class DashboardUserChangeRole(APIView):
    permission_classes = [CanManageUsers]

    def post(self, request, pk):
        try:
            user = User.objects.get(id=pk)
        except User.DoesNotExist:
            return error_response(message="User not found", code=404)

        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_role = user.user_role
        user.user_role = serializer.validated_data['user_role']
        user.save(update_fields=['user_role'])

        AuditLog.log(
            user=request.user, action='change_role', target_type='user',
            target_id=pk, target_repr=str(user),
            details={'old_role': old_role, 'new_role': user.user_role},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'user_role': user.user_role},
            message="User role changed successfully",
            code=200
        )


class DashboardUserExport(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = User.objects.all().order_by('-created_time')

        # Apply filters from query params. An invalid filter must fail loudly:
        # silently dropping it would export every user instead of the subset
        # the operator asked for.
        filterset = UserFilter(request.query_params, queryset=qs)
        if not filterset.is_valid():
            return error_response(data=filterset.errors, message="Invalid filter parameters", code=400)
        qs = filterset.qs

        # Apply search
        search = request.query_params.get('search', '')
        if search:
            qs = qs.filter(
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="users_export.csv"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Username', 'First Name', 'Last Name', 'Phone', 'Email', 'Role', 'Active', 'Created'])
        for u in qs:
            writer.writerow([
                str(u.id), u.username, u.first_name, u.last_name,
                u.phone_number, u.email, u.user_role, u.is_active,
                u.created_time.isoformat()
            ])
        AuditLog.log(
            user=request.user, action='export', target_type='user',
            details={'count': qs.count(), 'filters': dict(request.query_params)},
            ip_address=get_client_ip(request),
        )
        return response


class DashboardUserBulkAction(APIView):
    permission_classes = [CanManageUsers]

    def post(self, request):
        serializer = UserBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']
        ids = serializer.validated_data['ids']

        users = User.objects.filter(id__in=ids)
        count = users.count()

        if action == 'activate':
            users.update(is_active=True)
        elif action == 'deactivate':
            users.update(is_active=False)
        elif action == 'delete':
            users.delete()
        elif action == 'change_role':
            users.update(user_role=serializer.validated_data['role'])

        AuditLog.log(
            user=request.user, action=f'bulk_{action}', target_type='user',
            details={'ids': [str(i) for i in ids], 'count': count},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'affected': count},
            message=f'Bulk {action} completed for {count} users',
            code=200
        )
