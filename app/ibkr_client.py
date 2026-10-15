import asyncio
import logging
import httpx
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, List
from ib_async import IB, Contract, Order, OrderStatus, Trade

from .config import settings

logger = logging.getLogger(__name__)

# Statuses IBKR reports while an order submission is still in flight.
_PENDING_STATUSES = (OrderStatus.PendingSubmit, OrderStatus.ApiPending)


def describe_failure(trade: Trade) -> str:
    """Build a human-readable reason from the most recent IBKR log entry."""
    for entry in reversed(trade.log):
        if entry.errorCode:
            return f"{entry.message} (error {entry.errorCode})"
    return trade.orderStatus.status


def round_to_tick(price: float, min_tick: float) -> float:
    """Snap a price onto the instrument's tick grid.

    IBKR rejects off-tick prices with error 110, which surfaces as a
    ValidationError on the order rather than an exception.
    """
    if not min_tick or min_tick <= 0:
        return round(price, 2)
    step = Decimal(str(min_tick))
    snapped = (Decimal(str(price)) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    return float(snapped)

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

    async def get_min_tick(self, contract: Contract) -> float:
        """Fetch the minimum price increment IBKR accepts for a contract"""
        details = await self.ib.reqContractDetailsAsync(contract)
        return details[0].minTick if details else 0.0

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
        await self.wait_for_ack(trade)
        return trade

    async def place_bracket(self, contract: Contract, parent: Order, children: List[Order]):
        """Place a bracket: parent held back, children linked then transmitted.

        Returns the parent trade once IBKR has acknowledged or rejected it.
        Raises RuntimeError if the parent is rejected.
        """
        parent_trade = self.ib.placeOrder(contract, parent)
        # IBKR assigns the orderId synchronously in placeOrder, so the children
        # can be parented immediately without waiting on a round trip.
        for child in children:
            child.parentId = parent.orderId
            self.ib.placeOrder(contract, child)

        # The last child's transmit releases the whole group, so only wait on
        # the parent: a rejected parent rejects the bracket.
        await self.wait_for_ack(parent_trade)

        if parent_trade.orderStatus.status == OrderStatus.ValidationError:
            raise RuntimeError(f"IBKR rejected the order: {describe_failure(parent_trade)}")
        return parent_trade

    async def wait_for_ack(self, trade: Trade, timeout: float = 5.0):
        """Wait for IBKR to move a trade out of its in-flight states."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while trade.orderStatus.status in _PENDING_STATUSES and loop.time() < deadline:
            await asyncio.sleep(0.05)
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
