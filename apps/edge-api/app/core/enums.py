from enum import StrEnum


class PermissionCode(StrEnum):
    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_WRITE = "organization:write"
    IDENTITY_READ = "identity:read"
    IDENTITY_WRITE = "identity:write"
    CATALOG_READ = "catalog:read"
    CATALOG_WRITE = "catalog:write"
    CATALOG_TENANT_WRITE = "catalog:tenant_write"
    ORDER_READ = "order:read"
    PAYMENT_READ = "payment:read"
    PAYMENT_RECONCILE = "payment:reconcile"
    KITCHEN_OPERATE = "kitchen:operate"
    REVIEW_READ = "review:read"
    REVIEW_RESOLVE = "review:resolve"
    REPORT_READ = "report:read"
    AUDIT_READ = "audit:read"
    AUDIT_TENANT_READ = "audit:tenant_read"


class QuoteStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class FulfillmentType(StrEnum):
    DINE_IN = "DINE_IN"
    TAKEAWAY = "TAKEAWAY"


class OrderStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentProvider(StrEnum):
    MOCK = "MOCK"
    ADYEN = "ADYEN"
    STRIPE = "STRIPE"
    SUMUP = "SUMUP"


class PaymentMethod(StrEnum):
    CARD = "CARD"
    CONTACTLESS = "CONTACTLESS"
    APPLE_PAY = "APPLE_PAY"
    GOOGLE_PAY = "GOOGLE_PAY"


class PaymentStatus(StrEnum):
    UNPAID = "UNPAID"
    INITIATED = "INITIATED"
    AUTHORIZING = "AUTHORIZING"
    PAID = "PAID"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    REFUND_PENDING = "REFUND_PENDING"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class PaymentTransactionKind(StrEnum):
    AUTHORISATION = "AUTHORISATION"
    STATUS_CHECK = "STATUS_CHECK"
    REFUND = "REFUND"


class RefundStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class FulfillmentStatus(StrEnum):
    NOT_RELEASED = "NOT_RELEASED"
    QUEUED = "QUEUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PREPARING = "PREPARING"
    READY = "READY"
    COLLECTED = "COLLECTED"
    ON_HOLD = "ON_HOLD"
    UNFULFILLABLE = "UNFULFILLABLE"
    CANCELLED = "CANCELLED"


class FulfillmentEndpointType(StrEnum):
    KDS = "KDS"
    PRINTER = "PRINTER"


class FulfillmentFailureReason(StrEnum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    STAFF_CAPACITY = "STAFF_CAPACITY"
    MANUAL_WORKSTATION_EQUIPMENT_FAILURE = "MANUAL_WORKSTATION_EQUIPMENT_FAILURE"
    ORDER_ERROR = "ORDER_ERROR"
    ALLERGEN_OR_RECIPE_ISSUE = "ALLERGEN_OR_RECIPE_ISSUE"
    STORE_CLOSING = "STORE_CLOSING"
    OTHER = "OTHER"


class ReviewStatus(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    ACTION_PENDING = "ACTION_PENDING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ReviewResolution(StrEnum):
    FULL_REFUND = "FULL_REFUND"
    PARTIAL_REFUND = "PARTIAL_REFUND"
    REMAKE = "REMAKE"
    SUBSTITUTION = "SUBSTITUTION"
    MANUALLY_FULFILLED = "MANUALLY_FULFILLED"
    NO_FINANCIAL_ACTION = "NO_FINANCIAL_ACTION"


class ReceiptType(StrEnum):
    SALE = "SALE"
    REFUND = "REFUND"


class PromotionType(StrEnum):
    PERCENTAGE = "PERCENTAGE"
    FIXED_AMOUNT = "FIXED_AMOUNT"


class PriceBookStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ProductStatus(StrEnum):
    """Publication state of a catalog product.

    A draft is editable but never reaches the customer terminal, which lets an
    administrator prepare a product—or a duplicate of one—before it goes live.
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class MockPaymentScenario(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    UNKNOWN = "UNKNOWN"


class IdempotencyStatus(StrEnum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"


class ActorType(StrEnum):
    USER = "USER"
    KIOSK = "KIOSK"
    SYSTEM = "SYSTEM"
    PROVIDER = "PROVIDER"
