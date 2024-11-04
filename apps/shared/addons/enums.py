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
    CARD = "card"
    CASH = 'cash'


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


class MessageStatuses(EnumBaseModel):
    DELIVERED = 'delivered'
    SEEN = 'seen'
    RESPONDED = 'responded'


class IntegrationTypes(EnumBaseModel):
    TELEGRAM = 'telegram'
    WHATSAPP = 'whatsapp'
    WEBSITE = 'website'
    INSTAGRAM = 'instagram'
