"""Lead serializers for the dashboard."""
from rest_framework import serializers

from apps.assistant.models import Lead


class DashboardLeadSerializer(serializers.ModelSerializer):
    assistant_name = serializers.CharField(source='assistant.name', read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id', 'full_name', 'phone_number', 'email', 'product',
            'metadata', 'status', 'platform', 'username', 'contacted',
            'assistant', 'assistant_name', 'created_time', 'updated_time',
        ]
        read_only_fields = ['created_time', 'updated_time']
