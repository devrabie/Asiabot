from typing import Optional
from pydantic import BaseModel, Field

class LoginResponse(BaseModel):
    nextUrl: Optional[str] = None
    message: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    message: Optional[str] = None
    # Add other fields if necessary

class BalanceResponse(BaseModel):
    # Define fields based on actual response if known, for now use flexible dict or specific fields
    # As legacy php didn't specify fields for get_balance, we can keep it generic or assume basics
    pass
