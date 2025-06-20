from django.contrib import admin
from .models import Feature, PricingPackage, Transaction, Card, Balance, Subscription, RetryPayment


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ('name', )
    search_fields = ('name', )


@admin.register(PricingPackage)
class PricingPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'description', 'request_count', 'created_time')
    search_fields = ('name', 'price', 'description')
    filter_horizontal = ('features',)
    readonly_fields = ('created_time', 'updated_time')


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
    readonly_fields = ('created_time', 'updated_time')

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
        user = obj.users.first()  # Get the first user from the related users
        return user.username if user else '-'
    get_username.short_description = 'Username'  # Column header
    get_username.admin_order_field = 'users__username'  # Enable sorting

@admin.register(RetryPayment)
class RetryPaymentAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'amount', 'status', 'retry_date', 'created_time')
    search_fields = ('subscription__pricing_package__name', 'amount', 'status', 'retry_date')
    list_filter = ('status', 'subscription')
    readonly_fields = ('created_time', 'updated_time')
