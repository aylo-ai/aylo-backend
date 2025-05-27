from django.contrib import admin
from .models import Feature, PricingPackage, Transaction, Card, Balance, Subscription


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name', 'description')


@admin.register(PricingPackage)
class PricingPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'description', 'request_count')
    search_fields = ('name', 'price', 'description')
    filter_horizontal = ('features',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'amount', 'currency', 'created_time')
    search_fields = ('user__first_name', 'user__last_name', 'user__phone_number', 'user__username')
    list_filter = ('status', 'user', 'transaction_type')


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'card_number', 'expiry_date', 'is_verified', 'created_time')
    search_fields = ('user__first_name', 'user__last_name', 'user__phone_number', 'user__username')
    list_filter = ('is_default', 'is_verified')


@admin.register(Balance)
class BalanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'currency')
    search_fields = ('user__first_name', 'user__last_name', 'user__phone_number', 'user__username')
    list_filter = ('currency', 'user')

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('pricing_package', 'start_date', 'end_date', 'status', )
    search_fields = ('pricing_package__name', 'start_date', 'end_date', 'status', )
    list_filter = ('status', 'pricing_package')
