from django.db import models

from apps.shared.models import BaseModel


class Feature(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'feature'

    def __str__(self):
        return self.name


class PricingPackage(BaseModel):
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    description = models.TextField(null=True, blank=True)
    features = models.ManyToManyField(Feature, related_name='pricing_packages')

    class Meta:
        db_table = 'pricing_package'

    def __str__(self):
        return self.name