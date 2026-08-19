from django.contrib import admin

from apps.shared.addons.crypto import mask_secret

from .models import (
    Balance,
    Card,
    CustomPackageRequest,
    Feature,
    PricingPackage,
    RetryPayment,
    Subscription,
    Transaction,
)


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ('name', )
    search_fields = ('name', )


@admin.register(PricingPackage)
class PricingPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'price', 'request_count', 'is_popular', 'is_active', 'created_time')
    search_fields = ('name', 'price', 'description')
    list_filter = ('type', 'is_active', 'is_popular')
    filter_horizontal = ('features',)
    readonly_fields = ('created_time', 'updated_time')


@admin.register(CustomPackageRequest)
class CustomPackageRequestAdmin(admin.ModelAdmin):
    list_display = (
        'company_name', 'full_name', 'phone_number',
        'expected_conversations', 'is_processed', 'created_time',
    )
    search_fields = ('company_name', 'full_name', 'phone_number', 'email')
    list_filter = ('is_processed', 'pricing_package')
    readonly_fields = ('created_time', 'updated_time', 'user', 'pricing_package')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'amount', 'currency', 'created_time')
    search_fields = ('user__first_name', 'user__last_name', 'user__phone_number', 'user__username')
    list_filter = ('status', 'user', 'transaction_type')
    readonly_fields = ('created_time', 'updated_time')

@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'card_number', 'expiry_date', 'is_verified', 'created_time')
    search_fields = ('user__first_name', 'user__last_name', 'user__phone_number', 'user__username')
    list_filter = ('is_default', 'is_verified')
    exclude = ('card_token',)
    readonly_fields = ('card_token_masked', 'created_time', 'updated_time')

    @admin.display(description="Card token")
    def card_token_masked(self, obj):
        return mask_secret(obj.card_token)

@admin.register(Balance)
class BalanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'currency', 'created_time')
    search_fields = ('user__first_name', 'user__last_name', 'user__phone_number', 'user__username')
    list_filter = ('currency', 'user')
    readonly_fields = ('created_time', 'updated_time')

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('get_username', 'pricing_package', 'start_date', 'end_date', 'status', 'created_time')
    list_filter = ('status', 'pricing_package')
    search_fields = ('users__username', 'users__phone_number')
    readonly_fields = ('created_time', 'updated_time')

    def get_username(self, obj):
        user = obj.users.first()
        return user.username if user else '-'
    get_username.short_description = 'Username'
    get_username.admin_order_field = 'users__username'

@admin.register(RetryPayment)
class RetryPaymentAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'amount', 'status', 'retry_date', 'created_time')
    search_fields = ('subscription__pricing_package__name', 'amount', 'status', 'retry_date')
    list_filter = ('status', 'subscription')
    readonly_fields = ('created_time', 'updated_time')
