from django.db.models import Q

from apps.integration.models import Integration


def owned_integrations(user):
    return Integration.objects.filter(Q(assistant__user=user) | Q(user=user))


class IntegrationOwnedQuerysetMixin:
    owner_path = ""

    def get_queryset(self):
        user = self.request.user
        prefix = f"{self.owner_path}__" if self.owner_path else ""
        return self.queryset.filter(
            Q(**{f"{prefix}assistant__user": user}) | Q(**{f"{prefix}user": user}),
        ).distinct()
