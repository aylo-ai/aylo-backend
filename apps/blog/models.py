from django.db import models
from django.utils.text import slugify
from apps.shared.models import BaseModel


class BlogPost(BaseModel):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    excerpt = models.TextField(max_length=500, help_text="Short description for SEO meta and cards")
    content = models.TextField(help_text="Full blog post content in HTML or Markdown")
    cover_image = models.URLField(max_length=500, null=True, blank=True)
    author = models.CharField(max_length=100, default="Aylo AI Team")
    tags = models.JSONField(default=list, blank=True, help_text="List of tags for filtering")
    target_keyword = models.CharField(max_length=200, null=True, blank=True, help_text="Primary SEO keyword")
    meta_title = models.CharField(max_length=70, null=True, blank=True, help_text="SEO title (max 70 chars)")
    meta_description = models.CharField(max_length=160, null=True, blank=True, help_text="SEO description (max 160 chars)")
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    read_time = models.PositiveIntegerField(default=5, help_text="Estimated read time in minutes")
    internal_links = models.JSONField(
        default=list, blank=True,
        help_text="List of internal link objects: [{\"label\": \"...\", \"section\": \"pricing\"}]"
    )

    class Meta:
        db_table = "blog_post"
        ordering = ["-published_at", "-created_time"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
            # Ensure uniqueness
            original_slug = self.slug
            counter = 1
            while BlogPost.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{original_slug}-{counter}"
                counter += 1
        super().save(*args, **kwargs)
