"""
Polymarket CLOB (Central Limit Order Book) API Client

The CLOB API handles order placement, cancellation, and order book data.
Endpoint: https://clob.polymarket.com
"""

import time
import hmac
import hashlib
import requests
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    GTC = "GTC"  # Good Till Cancelled
    FOK = "FOK"  # Fill Or Kill
    GTD = "GTD"  # Good Till Date


@dataclass
class OrderBookLevel:
    """Single price level in the order book."""
    price: float
    size: float


@dataclass
class OrderBook:
    """Order book for a token."""
    token_id: str
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    timestamp: int
    
    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None
    
    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None


@dataclass
class Trade:
    """A completed trade."""
    id: str
    token_id: str
    price: float
    size: float
    side: Side
    timestamp: int


class ClobClient:
    """
    Client for Polymarket's CLOB API.
    
    For read-only operations (order book, trades), no auth needed.
    For trading, requires API key + secret.
    """
    
    BASE_URL = "https://clob.polymarket.com"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        timeout: int = 30
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        self.timeout = timeout
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json"
        })
    
    def _sign_request(self, timestamp: int, method: str, path: str, body: str = "") -> str:
        """Generate HMAC signature for authenticated requests."""
        if not self.api_secret:
            raise ValueError("API secret required for signed requests")
        
        message = f"{timestamp}{method}{path}{body}"
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def _authenticated_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make an authenticated API request."""
        if not self.api_key or not self.api_secret:
            raise ValueError("API key and secret required")
        
        timestamp = int(time.time() * 1000)
        body = ""
        
        if data:
            import json
            body = json.dumps(data, separators=(",", ":"))
        
        signature = self._sign_request(timestamp, method, path, body)
        
        headers = {
            "POLY_API_KEY": self.api_key,
            "POLY_TIMESTAMP": str(timestamp),
            "POLY_SIGNATURE": signature
        }
        
        response = self.session.request(
            method,
            f"{self.BASE_URL}{path}",
            headers=headers,
            json=data if data else None,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        return response.json()
    
    # ==================== Public Endpoints ====================
    
    def get_order_book(self, token_id: str) -> OrderBook:
        """
        Get order book for a token.
        
        Args:
            token_id: The token's contract address
            
        Returns:
            OrderBook with bids and asks
        """
        response = self.session.get(
            f"{self.BASE_URL}/book",
            params={"token_id": token_id},
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        
        bids = [
            OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
            for b in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
            for a in data.get("asks", [])
        ]
        
        return OrderBook(
            token_id=token_id,
            bids=bids,
            asks=asks,
            timestamp=data.get("timestamp", int(time.time() * 1000))
        )
    
    def get_price(self, token_id: str, side: Side) -> Optional[float]:
        """
        Get the current best price for a side.
        
        Args:
            token_id: The token's contract address
            side: BUY or SELL
            
        Returns:
            Best available price or None
        """
        response = self.session.get(
            f"{self.BASE_URL}/price",
            params={"token_id": token_id, "side": side.value},
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        
        return float(data["price"]) if data.get("price") else None
    
    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        response = self.session.get(
            f"{self.BASE_URL}/midpoint",
            params={"token_id": token_id},
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        
        return float(data["mid"]) if data.get("mid") else None
    
    def get_spread(self, token_id: str) -> Optional[float]:
        """Get bid-ask spread for a token."""
        response = self.session.get(
            f"{self.BASE_URL}/spread",
            params={"token_id": token_id},
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        
        return float(data["spread"]) if data.get("spread") else None
    
    def get_last_trade_price(self, token_id: str) -> Optional[float]:
        """Get last trade price for a token."""
        response = self.session.get(
            f"{self.BASE_URL}/last-trade-price",
            params={"token_id": token_id},
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        
        return float(data["price"]) if data.get("price") else None
    
    def get_trades(
        self,
        token_id: str,
        limit: int = 100,
        before: Optional[int] = None,
        after: Optional[int] = None
    ) -> List[Trade]:
        """
        Get recent trades for a token.
        
        Args:
            token_id: The token's contract address
            limit: Max trades to return
            before: Get trades before this timestamp
            after: Get trades after this timestamp
            
        Returns:
            List of Trade objects
        """
        params = {"token_id": token_id, "limit": limit}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        
        response = self.session.get(
            f"{self.BASE_URL}/trades",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        trades = []
        for t in response.json():
            trades.append(Trade(
                id=t["id"],
                token_id=token_id,
                price=float(t["price"]),
                size=float(t["size"]),
                side=Side(t["side"]),
                timestamp=t["timestamp"]
            ))
        
        return trades
    
    # ==================== Authenticated Endpoints ====================
    
    def create_order(
        self,
        token_id: str,
        side: Side,
        price: float,
        size: float,
        order_type: OrderType = OrderType.GTC,
        expiration: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create a limit order.
        
        Args:
            token_id: Token to trade
            side: BUY or SELL
            price: Limit price (0.01 to 0.99)
            size: Order size in contracts
            order_type: GTC, FOK, or GTD
            expiration: Expiration timestamp for GTD orders
            
        Returns:
            Order confirmation
        """
        data = {
            "tokenID": token_id,
            "side": side.value,
            "price": str(price),
            "size": str(size),
            "orderType": order_type.value
        }
        
        if order_type == OrderType.GTD and expiration:
            data["expiration"] = expiration
        
        return self._authenticated_request("POST", "/order", data)
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order."""
        return self._authenticated_request("DELETE", f"/order/{order_id}")
    
    def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders."""
        return self._authenticated_request("DELETE", "/orders")
    
    def get_open_orders(self, token_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all open orders, optionally filtered by token."""
        path = "/orders"
        if token_id:
            path = f"/orders?token_id={token_id}"
        
        return self._authenticated_request("GET", path)


# Quick test
if __name__ == "__main__":
    client = ClobClient()
    
    # Example token ID (you'd get this from Gamma API)
    # This is just for demonstration
    print("CLOB Client initialized")
    print("For real usage, get token IDs from Gamma API markets")
