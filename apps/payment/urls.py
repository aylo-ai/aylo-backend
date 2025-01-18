from django.urls import path
import payment.views as views


urlpatterns = [
    path("features/", views.FeatureListCreateView.as_view()),
    path("features/<uuid:pk>/", views.FeatureRetrieveView.as_view()),
    path("pricing-packages/", views.PricingPackageListCreateView.as_view()),
    path("pricing-packages/<uuid:pk>/", views.PricingPackageRetrieveView.as_view()),

    path("payme/card/add/", views.CardCreateWithPaymeView.as_view()),
    path("payme/card/fill-balance/", views.PayWithCard.as_view()),
    path("cards/", views.CardListView.as_view()),
    path("cards/<uuid:pk>/", views.CardDetailView.as_view()),
    path("cards/<uuid:pk>/remove/", views.CardRemoveView.as_view()),
    path("cards/<uuid:pk>/set-default/", views.SetDefaultCard.as_view()),


]