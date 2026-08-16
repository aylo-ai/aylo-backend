from modeltranslation.translator import TranslationOptions, register

from apps.blog.models import BlogPost


@register(BlogPost)
class BlogPostTranslationOptions(TranslationOptions):
    fields = ('title', 'excerpt', 'content', 'meta_title', 'meta_description')
