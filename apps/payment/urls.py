from django.urls import path
import payment.views as views


urlpatterns = [
    path("features/", views.FeatureListCreateView.as_view()),
    path("features/<uuid:pk>/", views.FeatureRetrieveView.as_view()),
    path("pricing-packages/", views.PricingPackageListCreateView.as_view()),
    path("pricing-packages/<uuid:pk>/", views.PricingPackageRetrieveView.as_view()),
    # path("subscriptions/", views.SubscriptionRetrieveView.as_view()),
    path("subscriptions/create/", views.SubscriptionCreateView.as_view()),
    path("subscriptions/cancel/", views.SubscriptionCancellationView.as_view()),
    path("payme/card/add/", views.CardCreateWithPaymeView.as_view()),
    path("payme/card/fill-balance/", views.PayWithCard.as_view()),
    path("cards/", views.CardListView.as_view()),
    path("cards/<uuid:pk>/", views.CardDetailView.as_view()),
    path("cards/<uuid:pk>/remove/", views.CardRemoveView.as_view()),
    path("cards/<uuid:pk>/set-default/", views.SetDefaultCard.as_view()),
    #payme verification
    path("payme/get-verify-token/", views.PaymeGetVerifyCodeView.as_view()),
    path("payme/verify-code/", views.PaymeVerifyCodeView.as_view()),


    path("manual-payment/", views.ManualSubscriptionPaymentView.as_view()),


]