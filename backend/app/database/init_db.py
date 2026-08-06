from app.database.base import Base
from app.database.session import engine

# Import every model that should become a table
from app.models.product import Product

print("Registered tables:", list(Base.metadata.tables.keys()))

print("Creating tables...")
Base.metadata.create_all(bind=engine)

print("Done.")

from sqlalchemy import inspect

insp = inspect(engine)

print("Database tables:", insp.get_table_names())