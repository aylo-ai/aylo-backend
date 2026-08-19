def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')


def subscription_repr(subscription):
    package = subscription.pricing_package
    name = package.name if package else "no package"
    return f"{name} - {subscription.start_date} - {subscription.end_date}"
