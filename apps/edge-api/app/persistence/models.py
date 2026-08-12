"""Import every mapped model so Alembic sees one complete metadata graph."""

from app.modules.audit import models as audit_models
from app.modules.catalog import models as catalog_models
from app.modules.identity import models as identity_models
from app.modules.kitchen_fulfillment import models as kitchen_fulfillment_models
from app.modules.manual_review import models as manual_review_models
from app.modules.ordering import models as ordering_models
from app.modules.organization import models as organization_models
from app.modules.payments import models as payments_models
from app.modules.pricing_tax import models as pricing_tax_models
from app.modules.receipts import models as receipt_models

__all__ = [
    "audit_models",
    "catalog_models",
    "identity_models",
    "kitchen_fulfillment_models",
    "manual_review_models",
    "ordering_models",
    "organization_models",
    "payments_models",
    "pricing_tax_models",
    "receipt_models",
]
