from rest_framework import serializers


class StrictCharField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail('invalid')
        return super().to_internal_value(data)


def serialize_pricing_package(package):
    if not package:
        return None
    return {
        "id": package.id,
        "name": package.name,
        "type": package.type,
        "price": package.price,
        "request_count": package.request_count,
        "duration_days": package.duration_days,
        "discount_price": package.discount_price,
        "currency": package.currency,
    }


def serialize_subscription(subscription):
    if not subscription:
        return None
    return {
        "id": subscription.id,
        "pricing_package": serialize_pricing_package(subscription.pricing_package),
        "start_date": subscription.start_date,
        "end_date": subscription.end_date,
        "status": subscription.status,
        "remained_request_count": subscription.remained_request_count,
        "next_payment_date": subscription.next_payment_date,
        "auto_renew": subscription.auto_renew,
        "cancellation_reason": subscription.cancellation_reason,
        "last_payment_date": subscription.last_payment_date,
        "grace_period_days": subscription.grace_period_days,
    }
