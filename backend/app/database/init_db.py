from sqlalchemy import inspect

from app.database.base import Base
from app.database.session import engine

# Import every model that should become a table
from app.models.product import Product
from app.models.execution import Execution


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