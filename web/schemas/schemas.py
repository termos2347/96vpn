from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    source: str = "web"

class UserRegister(UserBase):
    email: EmailStr
    password: str
    username: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserProfile(UserBase):
    id: int
    username: Optional[str]
    is_active: bool
    expiry_date: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None

class PromptCard(BaseModel):
    id: int
    title: str
    description: str
    category: str
    usage_count: int
    rating: float

class PaymentCreate(BaseModel):
    user_id: int
    amount: float
    plan: str  # "monthly" или "quarterly"
    description: str

class PaymentResponse(BaseModel):
    payment_id: str
    status: str
    confirmation_url: Optional[str]
    created_at: datetime

class WebhookYookassa(BaseModel):
    type: str
    event: str
    object: dict

class SubscriptionInfo(BaseModel):
    is_active: bool
    days_remaining: Optional[int]
    expiry_date: Optional[datetime]
