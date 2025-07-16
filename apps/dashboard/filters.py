from django_filters import rest_framework as filters
from apps.user.models import User

class UserFilter(filters.FilterSet):
    date_range = filters.DateRangeFilter(field_name='created_time')
    
    class Meta:
        model = User
        fields = ['created_time']