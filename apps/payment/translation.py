from modeltranslation.translator import register, TranslationOptions
from apps.payment.models import Feature, PricingPackage

@register(Feature)
class FeatureTranslationOptions(TranslationOptions):
    fields = ('name',)

@register(PricingPackage)
class PricingPackageTranslationOptions(TranslationOptions):
    fields = ('name', 'description')