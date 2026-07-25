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
    STAFF = 'staff'


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
    BITRIX24 = 'bitrix24'
    AMOCRM = 'amocrm'
    BILLZ = 'billz'


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


class PricingPackageType(EnumBaseModel):
    FREE = 'free'
    CUSTOM = 'custom'
    PRO = 'pro'
    
class AuthTypes(EnumBaseModel):
    PHONE = 'phone'
    EMAIL = 'email'
    GOOGLE = 'google'
    APPLE = 'apple'

class SubscriptionStatuses(EnumBaseModel):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    CANCELLED = 'cancelled'

class NotificationTypes(EnumBaseModel):
    NEWS='news'
    FAILED='failed'
    SUCCESS='success'
    WARNING='warning'

class FileTypes(EnumBaseModel):
    GOOGLE_SPREADSHEET = 'google_spreadsheet'
    GOOGLE_DOCUMENT = 'google_document'

class LeadStatuses(EnumBaseModel):
    """Lifecycle of a captured lead.

    An earlier `new/registered/delivered/lost` version of this class used to sit
    further up the file and was silently shadowed by this one — Python keeps the
    last definition, so those four values were never the ones in effect. The
    duplicate has been removed; these are the real values, and the ones
    `assistant/tasks.py` writes.
    """
    NEW = 'new'
    ENGAGED = 'engaged'
    PARTIAL_INFO = 'partial_info'
    QUALIFIED = 'qualified'
    REJECTED = 'rejected'
    UNREACHABLE = 'unreachable'

class ActionType(EnumBaseModel):
    CONDITION = 'condition'
    MESSAGE = 'message'

class ButtonType(EnumBaseModel):
    WEBURL = 'web_url'
    POSTBACK = 'postback'

class ConditionType(EnumBaseModel):
    SUBSCRIBED = 'subscribed'

class FlowType(EnumBaseModel):
    COMMENT_RESPONSE = 'comment_response'

class FollowUpLogStatus(EnumBaseModel):
    PENDING = 'pending'
    SENT = 'sent'
    CANCELLED = 'cancelled'
    FAILED = 'failed'

class BroadcastStatuses(EnumBaseModel):
    PENDING = 'pending'
    SENDING = 'sending'
    COMPLETED = 'completed'
