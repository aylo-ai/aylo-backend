"""Instagram OAuth callback and the Meta-mandated deauthorize / data-deletion
endpoints.

All three are called by Meta, so their paths and payload shapes are frozen.
"""
import base64
import hashlib
import hmac
import json
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework.views import APIView

from apps.assistant.utils import owned_assistants
from apps.integration.gateways.instagram import instagram_service
from apps.integration.models import Integration, InstagramCommentResponse
from apps.integration.throttles import MetaDataRequestThrottle, OAuthCallbackThrottle
from apps.shared import http
from apps.shared.addons.enums import IntegrationTypes
from apps.shared.addons.validations import error_response, success_response
from config.settings import (
    INSTAGRAM_CLIENT_ID,
    INSTAGRAM_CLIENT_SECRET,
    INSTAGRAM_REDIRECT_URI,
)

logger = logging.getLogger(__name__)


class InstagramCallbackView(APIView):
    CLIENT_ID = INSTAGRAM_CLIENT_ID
    CLIENT_SECRET = INSTAGRAM_CLIENT_SECRET
    REDIRECT_URI = INSTAGRAM_REDIRECT_URI
    throttle_classes = [OAuthCallbackThrottle]

    @staticmethod
    def _owns_assistant(user, assistant_id):
        try:
            return owned_assistants(user).filter(id=assistant_id).exists()
        except (DjangoValidationError, ValueError):
            # A malformed id is "not yours", not a 500.
            return False

    def get(self, request, *args, **kwargs):
        # Get the authorization code from the query parameters
        user = request.user if request.user.is_authenticated else None
        code = request.query_params.get("code")
        assistant_id = request.query_params.get("assistant_id", None)
        is_automation_only = request.query_params.get("is_automation_only", "false")
        if not assistant_id and is_automation_only == "false":
            return error_response(message=_("Assistant ID topilmadi"), code=400)
        if not code:
            return error_response(message=_("Authorization code topilmadi"), code=400)

        # `assistant_id` arrives in the query string of an unauthenticated
        # endpoint and used to be written straight onto the new integration, so
        # anyone completing this flow with their own Instagram account could
        # bind it to another tenant's assistant: their DMs would then be
        # answered by the victim's agent, spending the victim's request quota
        # and reading back the victim's knowledge base. Bind it only when the
        # caller is authenticated and owns it; 404 rather than 403 so the
        # endpoint stays useless as an assistant-id oracle.
        if assistant_id:
            if user is None or not self._owns_assistant(user, assistant_id):
                return error_response(message=_("Assistant topilmadi"), code=404)

        # Exchange the authorization code for an access token
        token_url = "https://api.instagram.com/oauth/access_token"
        data = {
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": self.REDIRECT_URI,
            "code": code,
        }

        response = http.post(token_url, data=data)
        if response.status_code == 400:
            return error_response(message=response.json().get("error_message"), code=400)
        if response.status_code == 200:
            token_data = response.json()
            short_lived_access_token = token_data.get("access_token")
            # Fetch Instagram Business Accounts
            access_token = instagram_service.get_long_lived_access_token(short_lived_access_token)
        else:
            return error_response(message=_("Access token topilmadi"), code=400)
        # get instagram user profile
        user_profile = instagram_service.get_user_profile(access_token)
        if not user_profile:
            return error_response(message=_("Foydalanuvchi profili topilmadi"), code=400)

        instagram_account_id = user_profile.get("instagram_account_id")
        instagram_user_id = user_profile.get("instagram_user_id")
        if not instagram_account_id:
            logger.warning("Instagram profile returned no user_id; refusing to create an unroutable integration")
            return error_response(message=_("Foydalanuvchi profili topilmadi"), code=400)

        # A row for this identity may already exist. Matched explicitly rather
        # than with update_or_create, which raises MultipleObjectsReturned when
        # instagram_user_id and user are both NULL on more than one row — the
        # callback runs unauthenticated, so user is regularly NULL.
        existing = None
        if instagram_user_id:
            existing = Integration.objects.filter(
                instagram_user_id=instagram_user_id,
                user=user,
                integration_type=IntegrationTypes.INSTAGRAM.value,
            ).first()

        if existing and existing.instagram_account_id:
            logger.info("Instagram integration already exists for account %s", instagram_account_id)
            return error_response(message=_("Instagram integratsiyasi sizda mavjud"), code=400)

        # Any *other* row holding either identifier is a genuine duplicate.
        duplicates = Integration.instagram_by_id(instagram_account_id)
        if instagram_user_id:
            duplicates = duplicates | Integration.instagram_by_id(instagram_user_id)
        if existing:
            duplicates = duplicates.exclude(pk=existing.pk)
        if duplicates.exists():
            logger.info("Instagram integration already exists for account %s", instagram_account_id)
            return error_response(message=_("Instagram integratsiyasi sizda mavjud"), code=400)

        fields = {
            "assistant_id": assistant_id,
            "name": user_profile.get("instagram_username"),
            "api_token": access_token,
            "refresh_token": short_lived_access_token,
            "instagram_account_id": instagram_account_id,
            "instagram_username": user_profile.get("instagram_username"),
        }
        # Repair rather than get_or_create: a row left behind by an earlier failed
        # attempt keeps its blank identity columns (get_or_create skips its defaults
        # on a match), staying invisible to every webhook lookup.
        if existing:
            for field, value in fields.items():
                setattr(existing, field, value)
            existing.save()
            integration = existing
            logger.info("Instagram integration %s relinked", integration.id)
        else:
            integration = Integration.objects.create(
                instagram_user_id=instagram_user_id,
                user=user,
                integration_type=IntegrationTypes.INSTAGRAM.value,
                **fields,
            )
            logger.info("Instagram integration %s created", integration.id)

        # enable webhook for the integration
        url = f"https://graph.instagram.com/v22.0/me/subscribed_apps?access_token={access_token}&subscribed_fields=messages,comments"
        response = http.post(url)
        if response.status_code != 200:
            logger.warning("Instagram webhook subscription failed with status %s", response.status_code)
        if response.status_code == 200:
            return success_response(message=_("Integration muvaffaqiyatli yaratildi"), code=200)
        else:
            return error_response(message=_("Webhook topilmadi"), code=400)


def parse_signed_request(signed_request: str, app_secret: str):
    """Parse and validate a `signed_request` from Instagram/Facebook.

    Args:
        signed_request: The signed request string from Meta.
        app_secret: The Instagram app's secret key.

    Returns:
        dict or None: The decoded payload when the signature verifies, else None.
    """
    try:
        def base64_url_decode(input_str):
            input_str += '=' * ((4 - len(input_str) % 4) % 4)  # Proper padding
            return base64.urlsafe_b64decode(input_str.encode())

        encoded_sig, payload = signed_request.split('.', 1)

        # Decode the payload and signature
        decoded_sig = base64_url_decode(encoded_sig)
        decoded_payload = base64_url_decode(payload)
        data = json.loads(decoded_payload)

        # Generate expected signature
        expected_sig = hmac.new(
            app_secret.encode(),
            msg=payload.encode(),
            digestmod=hashlib.sha256
        ).digest()

        # Validate signature
        if not hmac.compare_digest(decoded_sig, expected_sig):
            logger.warning("Instagram signed request carried an invalid signature")
            return None

        return data

    except Exception:
        logger.exception("Error parsing Instagram signed request")
        return None


class InstagramDeauthorizeView(APIView):
    throttle_classes = [MetaDataRequestThrottle]

    def post(self, request, *args, **kwargs): # noqa
        # Facebook sends a signed request
        signed_request = request.data.get("signed_request")
        if not signed_request:
            return error_response(message="Signed request not found", code=400)

        data = parse_signed_request(signed_request, INSTAGRAM_CLIENT_SECRET)
        if not data:
            return error_response(message="Invalid signed request", code=400)

        user_id = data.get("user_id")
        if user_id:
            # Find and remove the user's Instagram integration
            try:
                # The signed request carries the app-scoped ID, which OAuth
                # stores in instagram_user_id — match either column.
                integration = Integration.instagram_by_id(user_id).first()
                if integration:
                    # Delete all related InstagramCommentResponse and their InstagramMedia
                    comment_responses = InstagramCommentResponse.objects.filter(integration=integration)
                    for response in comment_responses:
                        old_media = list(response.instagram_media.all())
                        for media in old_media:
                            media.delete()
                        response.delete()
                    # Delete the integration itself
                    integration.delete()
                    logger.info("Instagram user %s deauthorized the app; integration removed", user_id)
                else:
                    logger.info("Instagram user %s deauthorized the app but no integration was found", user_id)
                return success_response(message=_("Foydalanuvchi appni deauthorized qildi"), code=200)
            except Exception:
                logger.exception("Error during Instagram deauthorization")
                return error_response(message=_("Deauthorization xatolik"), code=500)
        else:
            return error_response(message=_("Foydalanuvchi ID topilmadi"), code=400)


class InstagramDataDeletionView(APIView):
    throttle_classes = [MetaDataRequestThrottle]

    def post(self, request, *args, **kwargs):
        signed_request = request.data.get("signed_request")

        if not signed_request:
            return error_response(message=_("Signed request topilmadi"), code=400)

        data = parse_signed_request(signed_request, INSTAGRAM_CLIENT_SECRET)
        if not data:
            return error_response(message="Invalid signed request", code=400)

        user_id = data.get("user_id")
        if user_id:
            # Process data deletion for the user
            logger.info("Instagram data deletion requested for user %s", user_id)
            return success_response(data={
                "url": "https://api.repli.uz/integration/instagram/data-deletion-status/",
                "confirmation_code": user_id
            }, code=200)
        else:
            return error_response(message="User ID not found in signed request", code=400)
