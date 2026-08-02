"""Shared view helpers local to the integration app."""
from django.db.models import Q

from apps.integration.models import Integration


def owned_integrations(user):
    """The `Integration` rows ``user`` owns, directly or through an assistant.

    The single definition of tenancy for this app. Views that resolve an
    integration from a URL parameter or a request body must go through it —
    filtering on the id alone hands every other tenant's channel, and the
    access token stored on it, to any authenticated caller.
    """
    return Integration.objects.filter(Q(assistant__user=user) | Q(user=user))


class IntegrationOwnedQuerysetMixin:
    """Scope a view's queryset to the rows the requesting user owns.

    Ownership always resolves back to an `Integration`, which is held either
    directly (`Integration.user`) or through its assistant
    (`Integration.assistant.user`). `owner_path` is the ORM path from this
    view's model to that integration — empty when the view *is* on Integration.

    This replaces the same eight-line `get_queryset` that was copy-pasted
    across nine views; the emitted query is unchanged.
    """

    #: ORM path from this view's model to the owning ``Integration``.
    owner_path = ""

    def get_queryset(self):
        user = self.request.user
        prefix = f"{self.owner_path}__" if self.owner_path else ""
        return self.queryset.filter(
            Q(**{f"{prefix}assistant__user": user}) | Q(**{f"{prefix}user": user}),
        ).distinct()
