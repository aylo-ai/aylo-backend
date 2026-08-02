"""Dashboard permission tests.

Regression coverage for the 2026-07-31 privilege-escalation fix: the generic
`RetrieveUpdateDestroyAPIView`s for users, subscriptions and transactions were
gated by `IsDashboardUser` (any staff role) on every method, including
PUT/PATCH/DELETE — silently bypassing the narrower `CanManageUsers` /
`CanManageFinance` permission that the sibling toggle-active/change-role and
cancel/extend/refund endpoints correctly required. A support_agent could PATCH
`user_role` to `super_admin`, or delete a user/subscription/transaction
outright, without ever touching the endpoints meant to gate those actions.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.payment.models import Subscription, Transaction
from apps.shared.addons.enums import (
    PaymentStatuses,
    SubscriptionStatuses,
    UserRoles,
)
from apps.user.models import User


def make_user(role, **kwargs):
    kwargs.setdefault("username", f"{role}-{User.objects.count()}")
    kwargs.setdefault("auth_type", "email")
    return User.objects.create(user_role=role, **kwargs)


class DashboardUserDetailPermissionTests(TestCase):
    def setUp(self):
        self.support_agent = make_user(UserRoles.SUPPORT_AGENT.value)
        self.admin = make_user(UserRoles.ADMIN.value)
        self.target = make_user(UserRoles.CUSTOMER.value)
        self.client = APIClient()

    def test_support_agent_cannot_change_role_via_detail_view(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.patch(
            f"/api/v1/dashboard/users/{self.target.id}/",
            {"user_role": UserRoles.SUPER_ADMIN.value},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.target.refresh_from_db()
        self.assertEqual(self.target.user_role, UserRoles.CUSTOMER.value)

    def test_support_agent_cannot_delete_user(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.delete(f"/api/v1/dashboard/users/{self.target.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(id=self.target.id).exists())

    def test_support_agent_can_still_read_user(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.get(f"/api/v1/dashboard/users/{self.target.id}/")
        self.assertEqual(response.status_code, 200)

    def test_admin_can_change_role_via_detail_view(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f"/api/v1/dashboard/users/{self.target.id}/",
            {"user_role": UserRoles.MANAGER.value},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.user_role, UserRoles.MANAGER.value)


class DashboardSubscriptionDetailPermissionTests(TestCase):
    def setUp(self):
        self.support_agent = make_user(UserRoles.SUPPORT_AGENT.value)
        self.admin = make_user(UserRoles.ADMIN.value)
        self.subscription = Subscription.objects.create(status=SubscriptionStatuses.ACTIVE.value)
        self.client = APIClient()

    def test_support_agent_cannot_edit_subscription(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.patch(
            f"/api/v1/dashboard/subscriptions/{self.subscription.id}/",
            {"remained_request_count": 999999},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.subscription.refresh_from_db()
        self.assertNotEqual(self.subscription.remained_request_count, 999999)

    def test_support_agent_cannot_delete_subscription(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.delete(f"/api/v1/dashboard/subscriptions/{self.subscription.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Subscription.objects.filter(id=self.subscription.id).exists())

    def test_support_agent_can_still_read_subscription(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.get(f"/api/v1/dashboard/subscriptions/{self.subscription.id}/")
        self.assertEqual(response.status_code, 200)

    def test_admin_can_edit_subscription(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f"/api/v1/dashboard/subscriptions/{self.subscription.id}/",
            {"remained_request_count": 42},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.remained_request_count, 42)


class DashboardTransactionDetailPermissionTests(TestCase):
    def setUp(self):
        self.support_agent = make_user(UserRoles.SUPPORT_AGENT.value)
        self.admin = make_user(UserRoles.ADMIN.value)
        self.transaction = Transaction.objects.create(
            amount=100000, status=PaymentStatuses.SUCCESS.value,
        )
        self.client = APIClient()

    def test_support_agent_cannot_edit_transaction(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.patch(
            f"/api/v1/dashboard/transactions/{self.transaction.id}/",
            {"status": PaymentStatuses.REFUNDED.value},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, PaymentStatuses.SUCCESS.value)

    def test_support_agent_cannot_delete_transaction(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.delete(f"/api/v1/dashboard/transactions/{self.transaction.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Transaction.objects.filter(id=self.transaction.id).exists())

    def test_support_agent_can_still_read_transaction(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.get(f"/api/v1/dashboard/transactions/{self.transaction.id}/")
        self.assertEqual(response.status_code, 200)

    def test_admin_can_edit_transaction(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f"/api/v1/dashboard/transactions/{self.transaction.id}/",
            {"status": PaymentStatuses.REFUNDED.value},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, PaymentStatuses.REFUNDED.value)
