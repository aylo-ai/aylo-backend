from django.urls import path
import blog.views as views


urlpatterns = [
    path("posts/", views.BlogPostListView.as_view()),
    path("posts/<slug:slug>/", views.BlogPostDetailView.as_view()),
]
