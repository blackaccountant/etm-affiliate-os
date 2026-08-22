from sqlalchemy import inspect

from app.database.base import Base
from app.database.session import engine

import app.models

# Import every model that should become a table
from app.models.product import Product
from app.models.execution import Execution
from app.models.product_intelligence_history import (
    ProductIntelligenceHistory,
)
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.content_seo_score import ContentSEOScore
from app.models.content_approval import ContentApproval
from app.models.publishing_queue import PublishingQueue
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import (
    AffiliatePayoutAttempt,
)


print("=" * 50)
print("Initializing Database")
print("=" * 50)

print("Registered tables:")
for table in Base.metadata.tables.keys():
    print(f" - {table}")

print("\nCreating tables...")
Base.metadata.create_all(bind=engine)

insp = inspect(engine)

print("\nDatabase tables:")
for table in insp.get_table_names():
    print(f" - {table}")

print("\nDatabase initialization complete.")