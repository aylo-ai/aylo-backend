from rest_framework import serializers

from apps.blog.models import BlogPost


class BlogPostListSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = [
            "id",
            "title",
            "slug",
            "excerpt",
            "cover_image",
            "author",
            "tags",
            "target_keyword",
            "published_at",
            "read_time",
            "internal_links",
        ]


class BlogPostDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = [
            "id",
            "title",
            "slug",
            "excerpt",
            "content",
            "cover_image",
            "author",
            "tags",
            "target_keyword",
            "meta_title",
            "meta_description",
            "published_at",
            "read_time",
            "internal_links",
            "created_time",
            "updated_time",
        ]
