from django.contrib import admin
from .models import Feature, PricingPackage


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name', 'description')


@admin.register(PricingPackage)
class PricingPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'description')
    search_fields = ('name', 'price', 'description')
    filter_horizontal = ('features',)

