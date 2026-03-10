from django.contrib import admin
from apps.blog.models import BlogPost


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "is_published", "published_at", "read_time"]
    list_filter = ["is_published", "published_at"]
    search_fields = ["title", "excerpt", "content"]
    prepopulated_fields = {"slug": ("title",)}
    ordering = ["-published_at"]
