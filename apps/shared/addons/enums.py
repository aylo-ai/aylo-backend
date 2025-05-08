from enum import Enum


class EnumBaseModel(Enum):
    @classmethod
    def choices(cls):
        return [(key.value, key.name) for key in cls]


class UserRoles(EnumBaseModel):
    SUPER_ADMIN = 'super_admin'
    ADMIN = 'admin'
    MANAGER = 'manager'
    SUPPORT_AGENT = 'support_agent'
    CUSTOMER = 'customer'


class PaymentMethods(EnumBaseModel):
    PAYME = 'payme'
    CLICK = 'click'
    PAYNET = 'paynet'
    UZUM = 'uzum'


class ConversationStatuses(EnumBaseModel):
    OPEN = 'open'
    CLOSED = 'closed'
    PENDING = 'pending'
    ESCALATED = 'escalated'


class MessageTypes(EnumBaseModel):
    TEXT = 'text'
    IMAGE = 'image'
    VIDEO = 'video'
    AUDIO = 'audio'
    FILE = 'file'


class NotificationPreferences(EnumBaseModel):
    EMAIL = 'email'
    SMS = 'sms'
    PUSH = 'push'


class TemplateCategories(EnumBaseModel):
    GREETING = 'greeting'
    CLOSURE = 'closure'
    FOLLOW_UP = 'follow_up'
    FAQ = 'faq'


class EscalationActions(EnumBaseModel):
    NOTIFY_ADMIN = 'notify_admin'
    ASSIGN_TO_MANAGER = 'assign_to_manager'
    AUTO_RESPONSE = 'auto_response'


class SessionStatus(EnumBaseModel):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    EXPIRED = 'expired'


class AssistantLanguages(EnumBaseModel):
    ENGLISH = 'english'
    RUSSIAN = 'russian'
    UZBEK = 'uzbek'
    KAZAKH = 'kazakh'


class PersonalityStyles(EnumBaseModel):
    FORMAL = 'formal'
    FRIENDLY = 'friendly'
    PROFESSIONAL = 'professional'
    CASUAL = 'casual'
    INFORMATIVE = 'informative'


class SenderTypes(EnumBaseModel):
    ASSISTANT = 'assistant'
    USER = 'user'
    ADMIN = 'admin'


class MessageStatuses(EnumBaseModel):
    DELIVERED = 'delivered'
    SEEN = 'seen'
    RESPONDED = 'responded'


class IntegrationTypes(EnumBaseModel):
    TELEGRAM = 'telegram'
    WHATSAPP = 'whatsapp'
    WEBSITE = 'website'
    INSTAGRAM = 'instagram'


class ConversationPlatforms(EnumBaseModel):
    TELEGRAM = 'telegram'
    WHATSAPP = 'whatsapp'
    WEBSITE = 'website'
    INSTAGRAM = 'instagram'
    EMAIL = 'email'
    SMS = 'sms'
    PHONE = 'phone'
    OTHER = 'other'


class PaymentStatuses(EnumBaseModel):
    DRAFT = 'draft'
    SUCCESS = 'success'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'


class CurrencyType(EnumBaseModel):
    UZS = 'uzs'
    USD = 'usd'
    RUB = 'rub'
    EUR = 'eur'
    KZT = 'kzt'


class TransactionTypes(EnumBaseModel):
    DEPOSIT = 'deposit'
    WITHDRAW = 'withdraw'


class LeadStatuses(EnumBaseModel):
    NEW = 'new'
    REGISTERED = 'registered'
    DELIVERED = 'delivered'
    LOST = 'lost'
