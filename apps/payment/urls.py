from django.urls import path
import payment.views as views


urlpatterns = [
    path("features/", views.FeatureListCreateView.as_view()),
    path("features/<uuid:pk>/", views.FeatureRetrieveView.as_view()),
    path("pricing-packages/", views.PricingPackageListCreateView.as_view()),
    path("pricing-packages/<uuid:pk>/", views.PricingPackageRetrieveView.as_view()),
]