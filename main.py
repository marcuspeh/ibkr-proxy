import logging
from fastapi import FastAPI, Header, HTTPException
from typing import Optional, Dict, List

from ibkr_client import IBKRClient
from config import settings
from models import (
    LimitOrderRequest, MarketOrderRequest, BracketOrderRequest, UpdateOrderRequest,
    OrderResponse, BracketOrderResponse, PositionResponse, HealthResponse,
    OpenOrderResponse, OHLCResponse, AccountNAVResponse
)
from ib_async import LimitOrder, MarketOrder, BracketOrder as IBBracketOrder

from contextlib import asynccontextmanager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # IBKR initialization inside the lifespan to ensure it uses the same loop
    try:
        await ibkr.connect()
    except Exception as e:
        logger.error(f"Startup failed: {e}")
    yield
    await ibkr.disconnect()

app = FastAPI(title="IBKR Broker Proxy", lifespan=lifespan)
# Don't initialize IB() here, do it inside connect()
ibkr = IBKRClient()

# In-memory idempotency cache
idempotency_cache: Dict[str, dict] = {}

async def get_idempotent_response(x_idempotency_key: Optional[str]):
    if x_idempotency_key and x_idempotency_key in idempotency_cache:
        logger.info(f"Returning cached response for key: {x_idempotency_key}")
        return idempotency_cache[x_idempotency_key]
    return None

@app.get("/health", response_model=HealthResponse)
async def health():
    is_connected = ibkr.is_connected()
    return HealthResponse(
        status="connected" if is_connected else "disconnected",
        ibkr_connected=is_connected,
        client_id=settings.IBKR_CLIENT_ID
    )

@app.get("/positions", response_model=list[PositionResponse])
async def get_positions():
    if not ibkr.is_connected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    positions = await ibkr.get_positions()

    response = []
    for position in positions:
        positionResponse = PositionResponse(
            conId=position.contract.conId,
            symbol=position.contract.symbol,
            quantity=position.position,
            averageCost=position.avgCost
        )
        response.append(positionResponse)
        
    return response

@app.get("/account/nav", response_model=AccountNAVResponse)
async def get_account_nav():
    if not ibkr.is_connected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    nav_data = await ibkr.get_account_nav()
    if not nav_data:
        raise HTTPException(status_code=404, detail="NAV data not found")
    return AccountNAVResponse(**nav_data)

@app.get("/orders/open", response_model=list[OpenOrderResponse])
async def get_open_orders():
    if not ibkr.is_connected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    open_orders = await ibkr.get_open_orders()
    response = []
    for order in open_orders:
        orderResponse = OpenOrderResponse(
            permId=order.permId,
            orderId=order.orderId,
            symbol=order.contract.symbol,
            action=order.action,
            totalQuantity=order.totalQuantity,
            lmtPrice=getattr(order, 'lmtPrice', None),
            auxPrice=getattr(order, 'auxPrice', None),
            status=order.orderStatus.status,
            remaining=order.orderStatus.remaining
        )
        response.append(orderResponse)
        
    return response

@app.get("/ohlc", response_model=List[OHLCResponse])
async def get_ohlc(symbols: str):
    """
    Get OHLC data for a list of tickers for the current day.
    'symbols' should be a comma-separated string of tickers (e.g., "AAPL,MSFT,TSLA").
    """
    if not ibkr.is_connected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    
    ticker_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No symbols provided")
        
    ohlc_data = await ibkr.get_ohlc(ticker_list)
    return [OHLCResponse(**data) for data in ohlc_data]

@app.post("/orders/limit", response_model=OrderResponse)
async def place_limit_order(
    req: LimitOrderRequest, 
    x_idempotency_key: Optional[str] = Header(None)
):
    # Check cache
    cached = await get_idempotent_response(x_idempotency_key)
    if cached: 
        return cached

    try:
        contract = await ibkr.qualify_contract(req.symbol, req.secType, req.currency, req.exchange)
        order = LimitOrder(
            req.action, req.totalQuantity, req.lmtPrice, 
            orderRef=req.orderRef,
            outsideRth=req.outsideRth
        )
        trade = await ibkr.place_order(contract, order)
        
        res = OrderResponse(
            permId=trade.order.permId,
            orderId=trade.order.orderId,
            status=trade.orderStatus.status
        ).dict()
        
        if x_idempotency_key:
            idempotency_cache[x_idempotency_key] = res
        return res
    except Exception as e:
        logger.error(f"Order placement failed: {e}")
        raise HTTPException(status_code=500, detail=f"IBKR Error: {str(e)}")

@app.post("/orders/market", response_model=OrderResponse)
async def place_market_order(
    req: MarketOrderRequest, 
    x_idempotency_key: Optional[str] = Header(None)
):
    cached = await get_idempotent_response(x_idempotency_key)
    if cached: 
        return cached

    try:
        contract = await ibkr.qualify_contract(req.symbol, req.secType, req.currency, req.exchange)
        order = MarketOrder(
            req.action, req.totalQuantity, 
            orderRef=req.orderRef,
            outsideRth=req.outsideRth
        )
        trade = await ibkr.place_order(contract, order)
        
        res = OrderResponse(
            permId=trade.order.permId,
            orderId=trade.order.orderId,
            status=trade.orderStatus.status
        ).dict()
        
        if x_idempotency_key:
            idempotency_cache[x_idempotency_key] = res
        return res
    except Exception as e:
        logger.error(f"Order placement failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/orders/bracket", response_model=BracketOrderResponse)
async def place_bracket_order(
    req: BracketOrderRequest, 
    x_idempotency_key: Optional[str] = Header(None)
):
    cached = await get_idempotent_response(x_idempotency_key)
    if cached: return cached

    try:
        contract = await ibkr.qualify_contract(req.symbol, req.secType, req.currency, req.exchange)
        bracket = IBBracketOrder(
            req.action, req.totalQuantity, req.lmtPrice, req.tpPrice, req.slPrice,
            orderRef=req.orderRef
        )
        
        # Enable outsideRth for all orders; GTC only for children (TP/SL)
        for i, o in enumerate(bracket):
            o.outsideRth = True
            if i > 0:  # Children are TP and SL
                o.tif = 'GTC'
            else:
                o.tif = 'DAY'  # Parent is DAY
        
        # Place the parent order (entry)
        parent_trade = await ibkr.place_order(contract, bracket[0])
        # Place children
        for o in bracket[1:]:
            ibkr.ib.placeOrder(contract, o)
            
        res = BracketOrderResponse(
            parentPermId=parent_trade.order.permId,
            parentOrderId=parent_trade.order.orderId,
            status=parent_trade.orderStatus.status
        ).dict()
        
        if x_idempotency_key:
            idempotency_cache[x_idempotency_key] = res
        return res
    except Exception as e:
        logger.error(f"Bracket order failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/orders/{order_id}")
async def cancel_order(order_id: int):
    success = await ibkr.cancel_order(order_id)
    if not success:
        raise HTTPException(status_code=404, detail="Order not found or already cancelled")
    return {"status": "cancellation_requested", "order_id": order_id}

@app.put("/orders/{order_id}", response_model=OrderResponse)
async def update_order(order_id: int, req: UpdateOrderRequest):
    if not ibkr.is_connected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    
    trade = await ibkr.update_order(order_id, req.lmtPrice, req.auxPrice, req.totalQuantity)
    if not trade:
        raise HTTPException(status_code=404, detail="Order not found or not in a modifiable state")
    
    return OrderResponse(
        permId=trade.order.permId,
        orderId=trade.order.orderId,
        status=trade.orderStatus.status
    )

if __name__ == "__main__":
    import uvicorn
    # Use a single worker to avoid event loop issues with some asyncio libraries
    uvicorn.run("main:app", host=settings.PROXY_HOST, port=settings.PROXY_PORT, workers=1)
