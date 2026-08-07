from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, HttpUrl


class ProductBase(BaseModel):
    name: str
    website: HttpUrl
    affiliate_program: str
    affiliate_url: HttpUrl
    commission_type: str
    commission_value: str
    cookie_duration: str
    category: str
    status: str = "active"


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    website: Optional[HttpUrl] = None
    affiliate_program: Optional[str] = None
    affiliate_url: Optional[HttpUrl] = None
    commission_type: Optional[str] = None
    commission_value: Optional[str] = None
    cookie_duration: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None


class ProductResponse(ProductBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)