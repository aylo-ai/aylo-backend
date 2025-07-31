from django.urls import path

from mcpdatabase import views

urlpatterns = [
    path("assistant/<str:pk>/mcpdatabase/", views.MCPDatabaseView.as_view(), name="mcpdatabase"),
    path("mcpdatabase/<str:pk>/connection/", views.MCPDatabaseConnectionView.as_view(), name="mcpdatabase_connection"),
]
