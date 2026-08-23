from pydantic import BaseModel
from typing import Optional

class ContractBase(BaseModel):
    symbol: str
    secType: str = "STK"
    currency: str = "USD"
    exchange: str = "SMART"

class OrderBase(BaseModel):
    action: str  # BUY or SELL
    totalQuantity: int
    orderRef: Optional[str] = None
    outsideRth: bool = False

class LimitOrderRequest(ContractBase, OrderBase):
    lmtPrice: float

class MarketOrderRequest(ContractBase, OrderBase):
    pass

class BracketOrderRequest(ContractBase, OrderBase):
    lmtPrice: float
    tpPrice: float
    slPrice: float

class UpdateOrderRequest(BaseModel):
    lmtPrice: Optional[float] = None
    auxPrice: Optional[float] = None
    totalQuantity: Optional[int] = None

class OrderResponse(BaseModel):
    permId: int
    orderId: int
    status: str

class BracketOrderResponse(BaseModel):
    parentPermId: int
    parentOrderId: int
    status: str

class PositionResponse(BaseModel):
    conId: int
    symbol: str
    quantity: float
    averageCost: float

class AccountNAVResponse(BaseModel):
    account: str
    nav: float
    currency: str

class HealthResponse(BaseModel):
    status: str
    ibkr_connected: bool
    client_id: int

class OpenOrderResponse(BaseModel):
    permId: int
    orderId: int
    symbol: str
    action: str
    totalQuantity: float
    lmtPrice: Optional[float] = None
    auxPrice: Optional[float] = None
    status: str
    remaining: float

class OHLCResponse(BaseModel):
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    date: str
