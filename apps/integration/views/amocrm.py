import json
import logging
import secrets
import time
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions
from rest_framework.views import APIView

from apps.assistant.models import Assistant
from apps.integration.models import Integration
from apps.integration.throttles import OAuthCallbackThrottle
from apps.integration.views.mixins import owned_integrations
from apps.shared import http
from apps.shared.addons.enums import IntegrationTypes
from apps.shared.addons.redis import redis_client
from apps.shared.addons.validations import error_response, success_response

logger = logging.getLogger(__name__)

AMOCRM_ALLOWED_DOMAINS = ("amocrm.ru", "amocrm.com")


def is_amocrm_host(host):
    host = (host or "").strip().lower()
    if not host or any(char in host for char in "/\\@:?#"):
        return False
    return any(
        host == domain or host.endswith("." + domain)
        for domain in AMOCRM_ALLOWED_DOMAINS
    )


def owned_amocrm_integration(user, integration_id):
    if not integration_id:
        return None
    try:
        return owned_integrations(user).filter(
            id=integration_id, integration_type=IntegrationTypes.AMOCRM.value,
        ).first()
    except (DjangoValidationError, ValueError):
        return None


class AmoCRMOAuthInstallView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            subdomain = 'repli'
            user_id = request.user.id

            if not subdomain:
                return error_response(
                    message="Subdomain is required",
                    code=400
                )

            client_id = getattr(settings, 'AMOCRM_CLIENT_ID', None)
            client_secret = getattr(settings, 'AMOCRM_SECRET_KEY', None)

            if not client_id or not client_secret:
                return error_response(
                    message="amoCRM credentials not configured",
                    code=500
                )

            state = secrets.token_urlsafe(32)

            redis_client.setex(
                f"amocrm_oauth_state:{state}",
                300,
                json.dumps({
                    'user_id': str(user_id),
                    'subdomain': subdomain,
                    'client_id': client_id,
                })
            )

            redirect_uri = f"{settings.BASE_URL}/api/v1/integration/amocrm/"
            auth_params = {
                'response_type': 'code',
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'state': state
            }

            auth_url = f"https://www.amocrm.ru/oauth?{urlencode(auth_params)}"

            return success_response(
                data={
                    'auth_url': auth_url,
                    'state': state,
                    'subdomain': subdomain
                },
                message="amoCRM OAuth URL generated successfully",
                code=200
            )

        except Exception:
            logger.exception("Error generating amoCRM OAuth URL")
            return error_response(
                message="Error generating amoCRM OAuth URL",
                code=500
            )


class AmoCRMOAuthHandlerView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OAuthCallbackThrottle]

    def get(self, request):
        try:
            code = request.GET.get('code')
            state = request.GET.get('state')
            referer = request.GET.get('referer')
            error = request.GET.get('error')

            if error:
                return error_response(
                    message=f"OAuth error: {error}",
                    code=400
                )

            if not code or not state or not referer:
                return error_response(
                    message="Missing required OAuth parameters",
                    code=400
                )

            if not is_amocrm_host(referer):
                logger.warning("amoCRM callback rejected an off-domain referer")
                return error_response(
                    message="Invalid amoCRM domain",
                    code=400
                )

            stored_state = redis_client.get(f"amocrm_oauth_state:{state}")
            if not stored_state:
                return error_response(
                    message="Invalid or expired state parameter",
                    code=400
                )

            state_data = json.loads(stored_state)
            user_id = state_data.get('user_id')
            client_id = state_data.get('client_id')
            client_secret = getattr(settings, 'AMOCRM_SECRET_KEY', None)
            if not client_secret:
                logger.error("AMOCRM_SECRET_KEY is not configured; cannot complete OAuth")
                return error_response(
                    message="amoCRM credentials not configured",
                    code=500
                )

            token_url = f"https://{referer}/oauth2/access_token"
            token_data = {
                'grant_type': 'authorization_code',
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': f"{settings.BASE_URL}/api/v1/integration/amocrm/",
                'code': code
            }

            token_response = http.post(token_url, data=token_data)

            if token_response.status_code != 200:
                logger.warning("amoCRM token exchange failed with status %s", token_response.status_code)
                return error_response(
                    message="Failed to exchange code for token",
                    code=400
                )

            token_info = token_response.json()
            access_token = token_info.get('access_token')
            refresh_token = token_info.get('refresh_token')
            expires_in = token_info.get('expires_in')


            if not access_token:
                return error_response(
                    message="No access token received from amoCRM",
                    code=400
                )
            user_info_url = f"https://{referer}/api/v4/account"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            user_response = http.get(user_info_url, headers=headers)
            if user_response.status_code != 200:
                return error_response(
                    message="Failed to get user information from amoCRM",
                    code=400
                )

            user_info = user_response.json()
            account_id = user_info.get('id')
            assistant = Assistant.objects.filter(user_id=user_id).first()

            if not assistant:
                return error_response(
                    message="No assistant found for user",
                    code=404
                )

            integration, created = Integration.objects.get_or_create(
                assistant=assistant,
                integration_type=IntegrationTypes.AMOCRM.value,
                defaults={
                    'name': f"amoCRM - {referer}",
                    'api_token': access_token,
                    'metadata': {
                        'subdomain': referer,
                        'client_id': client_id,
                        'refresh_token': refresh_token,
                        'expires_in': expires_in,
                        'account_id': account_id,
                        'user_info': user_info
                    }
                }
            )

            if not created:
                integration.api_token = access_token
                integration.metadata.update({
                    'subdomain': referer,
                    'client_id': client_id,
                    'refresh_token': refresh_token,
                    'expires_in': expires_in,
                    'account_id': account_id,
                    'user_info': user_info
                })
                integration.save()

            redis_client.delete(f"amocrm_oauth_state:{state}")

            return success_response(
                data={
                    'integration_id': str(integration.id),
                    'subdomain': referer,
                    'account_id': account_id,
                    'user_info': user_info
                },
                message="amoCRM integration successful",
                code=200
            )

        except Exception:
            logger.exception("Error processing amoCRM OAuth callback")
            return error_response(
                message="Error processing amoCRM OAuth callback",
                code=500
            )


class AmoCRMTokenRefreshView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            integration_id = request.data.get('integration_id')
            if not integration_id:
                return error_response(
                    message="Integration ID is required",
                    code=400
                )

            integration = owned_amocrm_integration(request.user, integration_id)

            if not integration:
                return error_response(
                    message="amoCRM integration not found",
                    code=404
                )

            metadata = integration.metadata or {}
            refresh_token = metadata.get('refresh_token')
            subdomain = metadata.get('subdomain')
            client_id = metadata.get('client_id')
            client_secret = getattr(settings, 'AMOCRM_SECRET_KEY', None)

            if not refresh_token or not subdomain or not client_secret:
                return error_response(
                    message="Missing refresh token or credentials",
                    code=400
                )

            if not is_amocrm_host(subdomain):
                logger.warning("amoCRM refresh refused a stored off-domain subdomain")
                return error_response(
                    message="Invalid amoCRM domain",
                    code=400
                )

            token_url = f"https://{subdomain}/oauth2/access_token"
            token_data = {
                'grant_type': 'refresh_token',
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token
            }

            token_response = http.post(token_url, data=token_data)

            if token_response.status_code != 200:
                return error_response(
                    message="Failed to refresh token",
                    code=400
                )

            token_info = token_response.json()
            new_access_token = token_info.get('access_token')
            new_refresh_token = token_info.get('refresh_token')
            new_expires_in = token_info.get('expires_in')

            integration.api_token = new_access_token
            integration.metadata.update({
                'refresh_token': new_refresh_token,
                'expires_in': new_expires_in,
                'last_refresh': time.time()
            })
            integration.save()

            return success_response(
                data={
                    'integration_id': str(integration.id),
                    'expires_in': new_expires_in
                },
                message="Token refreshed successfully",
                code=200
            )

        except Exception:
            logger.exception("Error refreshing amoCRM token")
            return error_response(
                message="Error refreshing token",
                code=500
            )


class AmoCRMSetPipelineView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            integration_id = request.data.get('integration_id')
            pipeline_id = request.data.get('pipeline_id')
            if not integration_id or not pipeline_id:
                return error_response(
                    message="Integration ID and Pipeline ID are required",
                    code=400
                )

            if not str(pipeline_id).isdigit():
                return error_response(
                    message="Pipeline ID must be numeric",
                    code=400
                )

            integration = owned_amocrm_integration(request.user, integration_id)

            if not integration:
                return error_response(
                    message="amoCRM integration not found",
                    code=404
                )

            subdomain = integration.metadata.get('subdomain') if integration.metadata else 'repli.amocrm.ru'
            if not is_amocrm_host(subdomain):
                logger.warning("amoCRM set-pipeline refused a stored off-domain subdomain")
                return error_response(
                    message="Invalid amoCRM domain",
                    code=400
                )
            access_token = integration.api_token

            pipeline_url = f"https://{subdomain}/api/v4/leads/pipelines/{pipeline_id}"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            pipeline_response = http.get(pipeline_url, headers=headers)

            if pipeline_response.status_code != 200:
                return error_response(
                    message="Failed to get pipeline info",
                    code=400
                )

            pipeline_info = pipeline_response.json()
            pipeline_name = pipeline_info.get('name', f'Pipeline {pipeline_id}')

            integration.metadata.update({
                'pipeline_id': pipeline_id,
                'pipeline_name': pipeline_name,
                'pipeline_info': pipeline_info
            })
            integration.save()

            return success_response(
                data={
                    'pipeline_id': pipeline_id,
                    'pipeline_name': pipeline_name,
                    'integration_id': str(integration.id)
                },
                message="Pipeline set successfully",
                code=200
            )

        except Exception:
            logger.exception("Error setting amoCRM pipeline")
            return error_response(
                message="Error setting pipeline",
                code=500
            )
