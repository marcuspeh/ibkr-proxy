import asyncio
import logging
import httpx
from typing import Optional, List
from ib_async import IB, Contract, Order

from .config import settings

logger = logging.getLogger(__name__)

class IBKRClient:
    def __init__(self):
        self.ib = None
        self.webhook_client = None

    async def connect(self):
        """Establish connection to IBKR Gateway"""
        self.ib = IB()
        self.webhook_client = httpx.AsyncClient()
        
        try:
            await self.ib.connectAsync(
                settings.IBKR_HOST, 
                settings.IBKR_PORT, 
                clientId=settings.IBKR_CLIENT_ID
            )
            logger.info(f"Connected to IBKR at {settings.IBKR_HOST}:{settings.IBKR_PORT}")
            
            # Setup event handlers
            self.ib.execDetailsEvent += self.on_exec_details
            self.ib.orderStatusEvent += self.on_order_status
            
            # Start heartbeat/reconnect monitor if needed
            # ib-insync handles most reconnection logic automatically if configured
        except Exception as e:
            logger.error(f"Failed to connect to IBKR: {e}")
            raise

    async def disconnect(self):
        """Close connections"""
        self.ib.disconnect()
        await self.webhook_client.aclose()

    def is_connected(self) -> bool:
        return self.ib.isConnected()

    async def qualify_contract(self, symbol: str, secType: str, currency: str, exchange: str) -> Contract:
        """Qualify a contract to ensure it has a conId"""
        contract = Contract(symbol=symbol, secType=secType, currency=currency, exchange=exchange)
        qualified = await self.ib.qualifyContractsAsync(contract)
        if not qualified:
            raise ValueError(f"Contract not found: {symbol}")
        return qualified[0]

    async def on_exec_details(self, trade, fill):
        """Handle execution details and push to webhook"""
        logger.info(f"Fill received: {fill}")
        payload = {
            "permId": trade.order.permId,
            "execId": fill.execution.execId,
            "fillPrice": fill.execution.price,
            "fillQty": fill.execution.shares,
            "orderRef": trade.order.orderRef,
            "commission": fill.commissionReport.commission if fill.commissionReport else 0.0
        }
        await self.send_webhook("fills", payload)

    async def on_order_status(self, trade):
        """Handle order status changes and push to webhook"""
        logger.info(f"Order status changed: {trade.orderStatus.status}")
        payload = {
            "permId": trade.order.permId,
            "status": trade.orderStatus.status,
            "remaining": trade.orderStatus.remaining
        }
        await self.send_webhook("status", payload)

    async def send_webhook(self, event_type: str, payload: dict):
        """Send data to the configured webhook URL"""
        if not settings.WEBHOOK_URL:
            return
            
        url = f"{settings.WEBHOOK_URL}/{event_type}"
        try:
            response = await self.webhook_client.post(url, json=payload, timeout=5.0)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send webhook {event_type}: {e}")

    async def get_positions(self):
        """Fetch all current positions"""
        positions = self.ib.positions()
        return positions

    async def get_account_nav(self):
        """Fetch Net Liquidation Value (NAV) for the account"""
        values = self.ib.accountValues()
        # Look for NetLiquidation tag
        nav_item = next((v for v in values if v.tag == 'NetLiquidation'), None)
        if nav_item:
            return {
                "account": nav_item.account,
                "nav": float(nav_item.value),
                "currency": nav_item.currency
            }
        
        # Fallback to accountSummary if not in accountValues
        summary = self.ib.accountSummary()
        nav_item = next((s for s in summary if s.tag == 'NetLiquidation'), None)
        if nav_item:
            return {
                "account": nav_item.account,
                "nav": float(nav_item.value),
                "currency": nav_item.currency
            }
        return None

    async def get_open_orders(self):
        """Fetch all current orders"""
        orders = self.ib.openOrders()
        return orders

    async def place_order(self, contract: Contract, order: Order):
        """Place an order and return the trade object"""
        trade = self.ib.placeOrder(contract, order)
        # Wait briefly for permId to be assigned
        timeout = 2.0
        start_time = asyncio.get_event_loop().time()
        while not trade.order.permId and (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(0.1)
        return trade

    async def cancel_order(self, order_id: int):
        """Cancel an order by its orderId"""
        # Find the trade object first
        for trade in self.ib.openTrades():
            if trade.order.orderId == order_id:
                self.ib.cancelOrder(trade.order)
                return True
        return False

    async def update_order(self, order_id: int, lmtPrice: Optional[float] = None, auxPrice: Optional[float] = None, totalQuantity: Optional[int] = None):
        """Update an existing order's price (limit or stop) or quantity"""
        for trade in self.ib.openTrades():
            if trade.order.orderId == order_id:
                if lmtPrice is not None:
                    trade.order.lmtPrice = lmtPrice
                if auxPrice is not None:
                    trade.order.auxPrice = auxPrice
                if totalQuantity is not None:
                    trade.order.totalQuantity = totalQuantity
                
                logger.info(f"Updating order {order_id}: lmtPrice={lmtPrice}, auxPrice={auxPrice}, qty={totalQuantity}")
                # Re-place the order to update it
                updated_trade = self.ib.placeOrder(trade.contract, trade.order)
                return updated_trade
        return None

    async def get_ohlc(self, symbols: List[str]) -> List[dict]:
        """Fetch OHLC data for a list of symbols for the current day"""
        tasks = [self._get_single_ohlc(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def _get_single_ohlc(self, symbol: str) -> Optional[dict]:
        """Fetch OHLC data for a single symbol for the current day"""
        try:
            contract = await self.qualify_contract(symbol, "STK", "USD", "SMART")
            # Request historical data for the last day
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime='',
                durationStr='1 D',
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=True
            )
            if bars:
                bar = bars[-1]
                return {
                    "symbol": symbol,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "date": str(bar.date)
                }
            else:
                logger.warning(f"No OHLC data found for {symbol}")
        except Exception as e:
            logger.error(f"Failed to get OHLC for {symbol}: {e}")
        return None
