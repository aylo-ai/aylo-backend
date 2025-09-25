from apps.assistant.models import Lead
from django_filters import rest_framework as filters
from shared.addons.enums import LeadStatuses

class LeadFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=LeadStatuses.choices())

    class Meta:
        model = Lead
        fields = ['status']