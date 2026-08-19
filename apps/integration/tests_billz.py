import uuid
from unittest import mock

import requests
from django.test import SimpleTestCase, TestCase

from apps.integration.gateways import billz
from apps.integration.models import Integration
from apps.integration.views.billz import billz_status
from apps.shared.addons.enums import BillzSyncStatuses, IntegrationTypes

SECRET_TOKEN = "billz-secret-token"
ACCESS_TOKEN = "billz-access-token"


def _response(status_code=200, payload=None):
    response = mock.MagicMock(status_code=status_code)
    response.json.return_value = payload
    return response


class BillzLoginTests(SimpleTestCase):
    def test_login_exchanges_the_secret_token_for_an_access_token(self):
        with mock.patch.object(
            billz.http, "post",
            return_value=_response(200, {"data": {"access_token": ACCESS_TOKEN}}),
        ) as post:
            self.assertEqual(billz.login(SECRET_TOKEN), ACCESS_TOKEN)

        post.assert_called_once_with(billz.LOGIN_URL, json={"secret_token": SECRET_TOKEN})

    def test_login_returns_none_when_billz_rejects_the_secret_token(self):
        with mock.patch.object(billz.http, "post", return_value=_response(401, {})):
            self.assertIsNone(billz.login(SECRET_TOKEN))

    def test_login_returns_none_when_the_payload_has_no_access_token(self):
        for payload in ({"data": {}}, {"data": None}, {}):
            with self.subTest(payload=payload):
                with mock.patch.object(billz.http, "post", return_value=_response(200, payload)):
                    self.assertIsNone(billz.login(SECRET_TOKEN))

    def test_login_fails_soft_on_a_network_error(self):
        with mock.patch.object(
            billz.http, "post", side_effect=requests.RequestException("down"),
        ):
            self.assertIsNone(billz.login(SECRET_TOKEN))

    def test_login_fails_soft_on_an_unparseable_body(self):
        response = _response(200)
        response.json.side_effect = ValueError("not json")
        with mock.patch.object(billz.http, "post", return_value=response):
            self.assertIsNone(billz.login(SECRET_TOKEN))

    def test_login_without_a_secret_token_makes_no_request(self):
        with mock.patch.object(billz.http, "post") as post:
            self.assertIsNone(billz.login(""))
        post.assert_not_called()


class BillzFetchAuthTests(SimpleTestCase):
    def test_an_expired_access_token_raises_billz_auth_error(self):
        for status_code in billz.AUTH_STATUS_CODES:
            with self.subTest(status_code=status_code):
                with mock.patch.object(
                    billz.http, "get", return_value=_response(status_code, {}),
                ):
                    with self.assertRaises(billz.BillzAuthError):
                        billz.fetch_all_products(ACCESS_TOKEN)

    def test_a_network_error_still_fails_soft(self):
        with mock.patch.object(
            billz.http, "get", side_effect=requests.RequestException("down"),
        ):
            self.assertEqual(billz.fetch_all_products(ACCESS_TOKEN), [])

    def test_a_network_error_mid_walk_returns_the_pages_already_collected(self):
        with mock.patch.object(billz, "PAGE_LIMIT", 1), \
                mock.patch.object(billz.http, "get", side_effect=[
                    _response(200, {"products": [{"id": "p1", "name": "One"}]}),
                    requests.RequestException("down"),
                ]):
            products = billz.fetch_all_products(ACCESS_TOKEN)

        self.assertEqual([product["id"] for product in products], ["p1"])

    def test_the_access_token_is_sent_as_a_bearer_header(self):
        with mock.patch.object(
            billz.http, "get", return_value=_response(200, {"products": []}),
        ) as get:
            billz.fetch_all_products(ACCESS_TOKEN)

        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"], f"Bearer {ACCESS_TOKEN}",
        )


class BillzStatusPayloadTests(SimpleTestCase):
    def test_not_connected_shape(self):
        self.assertEqual(billz_status(None), {
            "connected": False,
            "id": None,
            "name": None,
            "is_active": False,
            "sync_status": BillzSyncStatuses.NEVER_SYNCED.value,
            "last_synced_at": None,
            "product_count": None,
        })

    def test_connected_shape(self):
        integration_id = uuid.uuid4()
        integration = Integration(
            id=integration_id,
            name="Billz",
            is_active=True,
            integration_type=IntegrationTypes.BILLZ.value,
            api_token=ACCESS_TOKEN,
            refresh_token=SECRET_TOKEN,
            metadata={
                "billz_products_file_id": "file-1",
                "billz_sync_status": BillzSyncStatuses.SYNCED.value,
                "billz_last_synced_at": "2026-08-19T06:10:00Z",
                "billz_product_count": 1423,
            },
        )

        self.assertEqual(billz_status(integration), {
            "connected": True,
            "id": str(integration_id),
            "name": "Billz",
            "is_active": True,
            "sync_status": BillzSyncStatuses.SYNCED.value,
            "last_synced_at": "2026-08-19T06:10:00Z",
            "product_count": 1423,
        })

    def test_a_connected_integration_that_has_never_synced_reports_never_synced(self):
        integration = Integration(
            id=uuid.uuid4(), name="Billz", is_active=True,
            integration_type=IntegrationTypes.BILLZ.value, metadata=None,
        )
        payload = billz_status(integration)

        self.assertEqual(payload["sync_status"], BillzSyncStatuses.NEVER_SYNCED.value)
        self.assertIsNone(payload["last_synced_at"])
        self.assertIsNone(payload["product_count"])

    def test_the_payload_never_carries_a_credential(self):
        integration = Integration(
            id=uuid.uuid4(), name="Billz", is_active=True,
            integration_type=IntegrationTypes.BILLZ.value,
            api_token=ACCESS_TOKEN, refresh_token=SECRET_TOKEN,
            metadata={"billz_products_file_id": "file-1"},
        )
        payload = billz_status(integration)

        self.assertNotIn("api_token", payload)
        self.assertNotIn("refresh_token", payload)
        self.assertNotIn(ACCESS_TOKEN, str(payload))
        self.assertNotIn(SECRET_TOKEN, str(payload))


class BillzSyncTaskTests(TestCase):
    def setUp(self):
        from apps.assistant.models import Assistant

        self.assistant = Assistant.objects.create(
            name="Shop", company_name="Shop LLC", vector_id="vs_billz",
        )
        self.integration = Integration.objects.create(
            assistant=self.assistant,
            name="Billz",
            integration_type=IntegrationTypes.BILLZ.value,
            api_token=ACCESS_TOKEN,
            refresh_token=SECRET_TOKEN,
            metadata={"billz_products_file_id": "old-file", "subdomain": "acme"},
        )

        from apps.integration.tasks import billz as billz_task

        self.task_module = billz_task
        self.fetch = mock.patch.object(billz_task.billz_client, "fetch_all_products").start()
        self.login = mock.patch.object(billz_task.billz_client, "login").start()
        self.kb = mock.patch.object(billz_task, "knowledge_base").start()
        self.kb.ensure_store.return_value = "vs_billz"
        self.kb.add_text.return_value = "new-file"
        self.addCleanup(mock.patch.stopall)

    def run_task(self):
        self.task_module.fetch_and_save_billz_products(str(self.integration.id))
        return Integration.objects.get(pk=self.integration.pk)

    def metadata(self):
        return Integration.objects.get(pk=self.integration.pk).metadata or {}


    def test_an_expired_access_token_is_re_exchanged_and_the_fetch_retried_once(self):
        products = [{"id": "p1", "name": "One"}]
        self.fetch.side_effect = [billz.BillzAuthError("401"), products]
        self.login.return_value = "fresh-access-token"

        reloaded = self.run_task()

        self.login.assert_called_once_with(SECRET_TOKEN)
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(self.fetch.call_args_list[1].args[0], "fresh-access-token")
        self.assertEqual(reloaded.api_token, "fresh-access-token")
        self.assertEqual(
            reloaded.metadata["billz_sync_status"], BillzSyncStatuses.SYNCED.value,
        )
        self.assertEqual(reloaded.metadata["billz_product_count"], 1)

    def test_the_refreshed_token_is_findable_by_its_hash(self):
        self.fetch.side_effect = [billz.BillzAuthError("401"), [{"id": "p1"}]]
        self.login.return_value = "fresh-access-token"

        self.run_task()

        self.assertTrue(Integration.objects.filter(api_token="fresh-access-token").exists())

    def test_a_failed_re_login_records_auth_failed_and_does_not_raise(self):
        self.fetch.side_effect = billz.BillzAuthError("401")
        self.login.return_value = None

        reloaded = self.run_task()

        self.assertEqual(
            reloaded.metadata["billz_sync_status"], BillzSyncStatuses.AUTH_FAILED.value,
        )
        self.assertEqual(self.fetch.call_count, 1)

    def test_a_missing_secret_token_records_auth_failed_without_attempting_a_login(self):
        Integration.objects.filter(pk=self.integration.pk).update(refresh_token=None)
        self.fetch.side_effect = billz.BillzAuthError("401")

        reloaded = self.run_task()

        self.login.assert_not_called()
        self.assertEqual(
            reloaded.metadata["billz_sync_status"], BillzSyncStatuses.AUTH_FAILED.value,
        )

    def test_a_token_refused_immediately_after_a_successful_login_records_auth_failed(self):
        self.fetch.side_effect = billz.BillzAuthError("401")
        self.login.return_value = "fresh-access-token"

        reloaded = self.run_task()

        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(
            reloaded.metadata["billz_sync_status"], BillzSyncStatuses.AUTH_FAILED.value,
        )


    def test_a_successful_sync_records_synced_with_a_count_and_a_timestamp(self):
        self.fetch.return_value = [{"id": "p1"}, {"id": "p2"}]

        reloaded = self.run_task()
        metadata = reloaded.metadata

        self.assertEqual(metadata["billz_sync_status"], BillzSyncStatuses.SYNCED.value)
        self.assertEqual(metadata["billz_product_count"], 2)
        self.assertEqual(metadata["billz_products_file_id"], "new-file")
        self.assertRegex(
            metadata["billz_last_synced_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )
        self.kb.delete_file.assert_called_once_with("vs_billz", "old-file")

    def test_the_status_is_syncing_while_the_fetch_is_in_flight(self):
        seen = []

        def fetch(_token):
            seen.append(self.metadata().get("billz_sync_status"))
            return [{"id": "p1"}]

        self.fetch.side_effect = fetch

        self.run_task()

        self.assertEqual(seen, [BillzSyncStatuses.SYNCING.value])

    def test_an_empty_catalogue_records_failed_and_keeps_the_previous_file(self):
        self.fetch.return_value = []

        reloaded = self.run_task()

        self.assertEqual(reloaded.metadata["billz_sync_status"], BillzSyncStatuses.FAILED.value)
        self.assertEqual(reloaded.metadata["billz_products_file_id"], "old-file")
        self.kb.add_text.assert_not_called()

    def test_a_failed_index_records_failed(self):
        self.fetch.return_value = [{"id": "p1"}]
        self.kb.add_text.return_value = None

        reloaded = self.run_task()

        self.assertEqual(reloaded.metadata["billz_sync_status"], BillzSyncStatuses.FAILED.value)

    def test_an_unexpected_error_records_failed_rather_than_leaving_it_syncing(self):
        self.fetch.side_effect = RuntimeError("boom")

        reloaded = self.run_task()

        self.assertEqual(reloaded.metadata["billz_sync_status"], BillzSyncStatuses.FAILED.value)


    def test_the_metadata_merge_preserves_unrelated_keys(self):
        self.fetch.return_value = [{"id": "p1"}]

        reloaded = self.run_task()

        self.assertEqual(reloaded.metadata["subdomain"], "acme")

    def test_the_superseded_epoch_timestamp_is_dropped(self):
        Integration.objects.filter(pk=self.integration.pk).update(
            metadata={"billz_products_file_id": "old-file", "billz_products_updated_at": 1.0},
        )
        self.fetch.return_value = [{"id": "p1"}]

        reloaded = self.run_task()

        self.assertNotIn("billz_products_updated_at", reloaded.metadata)
        self.assertIn("billz_last_synced_at", reloaded.metadata)

    def test_a_non_billz_integration_is_ignored(self):
        telegram = Integration.objects.create(
            assistant=self.assistant, name="tg",
            integration_type=IntegrationTypes.TELEGRAM.value, api_token="tg-token",
        )

        self.task_module.fetch_and_save_billz_products(str(telegram.id))

        self.fetch.assert_not_called()
        self.assertIsNone(Integration.objects.get(pk=telegram.pk).metadata)

    def test_the_hourly_beat_queues_every_active_billz_integration(self):
        with mock.patch.object(self.task_module.fetch_and_save_billz_products, "delay") as delay:
            self.task_module.update_billz_products_hourly()

        delay.assert_called_once_with(str(self.integration.id))


class BillzEndpointFixture(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient

        from apps.assistant.models import Assistant
        from apps.payment.models import Subscription
        from apps.shared.addons.enums import SubscriptionStatuses
        from apps.user.models import User

        def subscribed(username):
            subscription = Subscription.objects.create(
                status=SubscriptionStatuses.ACTIVE.value, remained_request_count=1000,
            )
            return User.objects.create(
                username=username, auth_type="email", subscription=subscription,
            )

        self.owner = subscribed("billz-owner")
        self.stranger = subscribed("billz-stranger")
        self.assistant = Assistant.objects.create(
            name="Owned", company_name="C", user=self.owner, vector_id="vs_owner",
        )
        self.stranger_assistant = Assistant.objects.create(
            name="Stranger", company_name="S", user=self.stranger, vector_id="vs_stranger",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def status_url(self, assistant=None):
        return f"/api/v1/integration/assistant/{(assistant or self.assistant).id}/billz/"

    def sync_url(self, integration):
        return f"/api/v1/integration/billz/{integration.id}/sync/"

    def connect(self, assistant=None, payload=None):
        with mock.patch.object(billz, "login", return_value=ACCESS_TOKEN), \
                mock.patch("apps.integration.tasks.fetch_and_save_billz_products"):
            with self.captureOnCommitCallbacks(execute=True):
                return self.client.post(
                    self.status_url(assistant),
                    payload if payload is not None else {"api_token": SECRET_TOKEN, "name": "Billz"},
                    format="json",
                )

    def make_integration(self, assistant=None, **kwargs):
        kwargs.setdefault("api_token", ACCESS_TOKEN)
        kwargs.setdefault("refresh_token", SECRET_TOKEN)
        return Integration.objects.create(
            assistant=assistant or self.assistant,
            name="Billz",
            integration_type=IntegrationTypes.BILLZ.value,
            **kwargs,
        )


class BillzStatusEndpointTests(BillzEndpointFixture):
    def test_not_connected(self):
        response = self.client.get(self.status_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], {
            "connected": False,
            "id": None,
            "name": None,
            "is_active": False,
            "sync_status": BillzSyncStatuses.NEVER_SYNCED.value,
            "last_synced_at": None,
            "product_count": None,
        })

    def test_connected(self):
        integration = self.make_integration(metadata={
            "billz_sync_status": BillzSyncStatuses.SYNCED.value,
            "billz_last_synced_at": "2026-08-19T06:10:00Z",
            "billz_product_count": 1423,
        })

        response = self.client.get(self.status_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], {
            "connected": True,
            "id": str(integration.id),
            "name": "Billz",
            "is_active": True,
            "sync_status": BillzSyncStatuses.SYNCED.value,
            "last_synced_at": "2026-08-19T06:10:00Z",
            "product_count": 1423,
        })

    def test_no_token_ever_reaches_the_response_body(self):
        self.make_integration()

        response = self.client.get(self.status_url())
        body = response.content.decode()

        self.assertNotIn("api_token", body)
        self.assertNotIn("refresh_token", body)
        self.assertNotIn(ACCESS_TOKEN, body)
        self.assertNotIn(SECRET_TOKEN, body)

    def test_another_tenants_assistant_is_not_found(self):
        self.make_integration(assistant=self.stranger_assistant)

        response = self.client.get(self.status_url(self.stranger_assistant))

        self.assertEqual(response.status_code, 404)


class BillzConnectEndpointTests(BillzEndpointFixture):
    def test_connecting_stores_the_access_token_and_keeps_the_secret_for_recovery(self):
        response = self.connect()

        self.assertEqual(response.status_code, 201, response.data)
        integration = Integration.objects.get(integration_type=IntegrationTypes.BILLZ.value)
        self.assertEqual(integration.api_token, ACCESS_TOKEN)
        self.assertEqual(integration.refresh_token, SECRET_TOKEN)
        self.assertEqual(integration.assistant_id, self.assistant.id)

    def test_connecting_answers_with_the_status_payload_and_queues_the_first_sync(self):
        with mock.patch.object(billz, "login", return_value=ACCESS_TOKEN), \
                mock.patch("apps.integration.tasks.fetch_and_save_billz_products") as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    self.status_url(), {"api_token": SECRET_TOKEN, "name": "Billz"},
                    format="json",
                )

        integration = Integration.objects.get(integration_type=IntegrationTypes.BILLZ.value)
        task.delay.assert_called_once_with(str(integration.id))
        self.assertEqual(response.data["data"], {
            "connected": True,
            "id": str(integration.id),
            "name": "Billz",
            "is_active": True,
            "sync_status": BillzSyncStatuses.SYNCING.value,
            "last_synced_at": None,
            "product_count": None,
        })

    def test_an_invalid_secret_token_is_refused(self):
        with mock.patch.object(billz, "login", return_value=None), \
                mock.patch("apps.integration.tasks.fetch_and_save_billz_products") as task:
            response = self.client.post(
                self.status_url(), {"api_token": "nope", "name": "Billz"}, format="json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Integration.objects.exists())
        task.delay.assert_not_called()

    def test_a_missing_token_is_refused_before_any_billz_call(self):
        with mock.patch.object(billz, "login") as login:
            response = self.client.post(self.status_url(), {"name": "Billz"}, format="json")

        self.assertEqual(response.status_code, 400)
        login.assert_not_called()

    def test_another_tenants_assistant_is_not_found(self):
        response = self.connect(assistant=self.stranger_assistant)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Integration.objects.exists())

    def test_reconnecting_refreshes_the_existing_row_instead_of_duplicating_it(self):
        existing = self.make_integration(
            api_token="stale-access", refresh_token="stale-secret",
            metadata={"billz_sync_status": BillzSyncStatuses.AUTH_FAILED.value,
                      "billz_products_file_id": "old-file"},
        )

        response = self.connect()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            Integration.objects.filter(integration_type=IntegrationTypes.BILLZ.value).count(), 1,
        )
        existing.refresh_from_db()
        self.assertEqual(existing.api_token, ACCESS_TOKEN)
        self.assertEqual(existing.refresh_token, SECRET_TOKEN)
        self.assertEqual(
            existing.metadata["billz_sync_status"], BillzSyncStatuses.SYNCING.value,
        )
        self.assertEqual(existing.metadata["billz_products_file_id"], "old-file")


class BillzSyncEndpointTests(BillzEndpointFixture):
    def test_a_manual_sync_is_accepted_and_queued(self):
        integration = self.make_integration(metadata={"billz_products_file_id": "old-file"})

        with mock.patch("apps.integration.tasks.fetch_and_save_billz_products") as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.sync_url(integration))

        self.assertEqual(response.status_code, 202)
        task.delay.assert_called_once_with(str(integration.id))
        self.assertEqual(response.data["data"], {
            "connected": True,
            "id": str(integration.id),
            "name": "Billz",
            "is_active": True,
            "sync_status": BillzSyncStatuses.SYNCING.value,
            "last_synced_at": None,
            "product_count": None,
        })
        integration.refresh_from_db()
        self.assertEqual(integration.metadata["billz_products_file_id"], "old-file")

    def test_another_tenants_integration_cannot_be_synced(self):
        integration = self.make_integration(assistant=self.stranger_assistant)

        with mock.patch("apps.integration.tasks.fetch_and_save_billz_products") as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.sync_url(integration))

        self.assertEqual(response.status_code, 404)
        task.delay.assert_not_called()

    def test_a_non_billz_integration_cannot_be_synced(self):
        telegram = Integration.objects.create(
            assistant=self.assistant, name="tg",
            integration_type=IntegrationTypes.TELEGRAM.value, api_token="tg-token",
        )

        with mock.patch("apps.integration.tasks.fetch_and_save_billz_products") as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.sync_url(telegram))

        self.assertEqual(response.status_code, 404)
        task.delay.assert_not_called()


class BillzDisconnectTests(BillzEndpointFixture):
    def test_deleting_the_integration_removes_the_catalogue_from_the_vector_store(self):
        integration = self.make_integration(metadata={"billz_products_file_id": "file-1"})

        with mock.patch("apps.integration.views.integrations.knowledge_base") as kb:
            response = self.client.delete(f"/api/v1/integration/integration/{integration.id}/")

        self.assertEqual(response.status_code, 204)
        kb.delete_file.assert_called_once_with("vs_owner", "file-1")
        self.assertFalse(Integration.objects.filter(pk=integration.pk).exists())

    def test_deleting_an_integration_that_never_synced_deletes_nothing(self):
        integration = self.make_integration(metadata=None)

        with mock.patch("apps.integration.views.integrations.knowledge_base") as kb:
            response = self.client.delete(f"/api/v1/integration/integration/{integration.id}/")

        self.assertEqual(response.status_code, 204)
        kb.delete_file.assert_not_called()
