from django.contrib import admin as django_admin
from django.test import TestCase

from apps.payment.admin import CardAdmin
from apps.payment.models import Card
from apps.payment.serializers import CardCreateSerializer
from apps.shared.tests.test_crypto import raw_column
from apps.user.models import User

CARD_TOKEN = "payme-live-card-token-abcdefgh"


class CardTokenAtRestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="card-owner", auth_type="email")
        self.card = Card.objects.create(
            user=self.user,
            card_token=CARD_TOKEN,
            card_number="8600123412341234",
            expiry_date="12/30",
        )

    def test_the_database_never_sees_the_token(self):
        stored = raw_column("Card", "card_token", self.card.id)
        self.assertNotIn(CARD_TOKEN, stored)

    def test_billing_can_still_read_it(self):
        self.assertEqual(Card.objects.get(pk=self.card.pk).card_token, CARD_TOKEN)

    def test_str_does_not_leak_the_token(self):
        self.assertNotIn(CARD_TOKEN, str(self.card))

    def test_serializer_never_returns_the_token(self):
        data = CardCreateSerializer(self.card).data
        self.assertNotIn("card_token", data)
        self.assertNotIn(CARD_TOKEN, str(data))

    def test_admin_neither_shows_nor_edits_the_token(self):
        model_admin = CardAdmin(Card, django_admin.site)
        self.assertIn("card_token", model_admin.exclude)
        self.assertNotIn(CARD_TOKEN, str(model_admin.list_display))
        self.assertEqual(model_admin.card_token_masked(self.card), f"***{CARD_TOKEN[-4:]}")
