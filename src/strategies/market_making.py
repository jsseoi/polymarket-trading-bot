"""
Market Making Strategy for Polymarket

Adapted from warproxxx/poly-maker's approach:
- Places two-sided quotes (bid + ask) around mid-price
- Captures spread as primary profit mechanism
- Risk management: stop-loss, take-profit, volatility guard
- Position management: max position limits, inventory skew

Polymarket fee model:
- Political/event markets: 0% fee for all
- Crypto markets: taker fee = C * 0.25 * (p*(1-p))^2, maker rebate = 20% of taker fee
- Sports markets: taker fee = C * 0.0175 * (p*(1-p))^1, maker rebate = 25% of taker fee
- Limit orders (our strategy) = maker = no fee + rebate income
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import math

from .base_strategy import BaseStrategy, Signal, Position


# --- Fee Model ---

@dataclass
class FeeConfig:
    """Polymarket fee configuration per market type."""
    fee_rate: float = 0.0       # Base fee rate
    exponent: float = 1.0       # Fee curve exponent
    maker_rebate_pct: float = 0.0  # Rebate as % of taker fee

    def taker_fee(self, price: float) -> float:
        """Calculate taker fee for a given price."""
        if self.fee_rate == 0:
            return 0.0
        return self.fee_rate * (price * (1 - price)) ** self.exponent

    def maker_rebate(self, price: float) -> float:
        """Calculate maker rebate (positive = income)."""
        return self.taker_fee(price) * self.maker_rebate_pct


# Predefined fee configs
FEE_POLITICAL = FeeConfig(fee_rate=0.0, exponent=1, maker_rebate_pct=0.0)
FEE_CRYPTO = FeeConfig(fee_rate=0.25, exponent=2, maker_rebate_pct=0.20)
FEE_SPORTS = FeeConfig(fee_rate=0.0175, exponent=1, maker_rebate_pct=0.25)


# --- Parameters ---

@dataclass
class MarketMakingParams:
    """Parameters controlling market-making behavior."""
    # Spread & quoting
    min_spread: float = 0.02        # Min spread to quote (2 cents)
    tick_size: float = 0.001        # Price increment

    # Position sizing
    trade_size: float = 50.0        # Base order size in dollars
    max_size: float = 200.0         # Max position per market in dollars
    min_order_size: float = 5.0     # Minimum order size in dollars

    # Risk management
    stop_loss_pct: float = -5.0     # Stop-loss trigger (% of position cost)
    take_profit_pct: float = 2.0    # Take-profit target (% above avg cost)
    volatility_threshold: float = 0.10  # Max price volatility (std of returns)

    # Cooldown after stop-loss
    sleep_period_hours: float = 1.0

    # Market filters
    min_liquidity: float = 5000.0
    min_volume_24h: float = 10000.0
    max_price: float = 0.90
    min_price: float = 0.10

    # Fee config
    fee_config: FeeConfig = field(default_factory=lambda: FEE_POLITICAL)

    # Inventory skew: bias quotes away from overweight side
    inventory_skew_factor: float = 0.3  # 0 = no skew, 1 = full skew


# --- Internal State ---

@dataclass
class InventoryState:
    """Tracks position inventory for a single market."""
    position: float = 0.0          # Contracts held (YES side)
    avg_price: float = 0.0         # Average entry price
    cost_basis: float = 0.0        # Total cost
    risk_off_until: Optional[datetime] = None

    def add(self, contracts: float, price: float):
        """Add to position, update average price."""
        if contracts <= 0:
            return
        new_cost = price * contracts
        total_contracts = self.position + contracts
        if total_contracts > 0:
            self.avg_price = (self.cost_basis + new_cost) / total_contracts
        self.position = total_contracts
        self.cost_basis = self.avg_price * self.position

    def remove(self, contracts: float) -> float:
        """Remove from position. Returns realized cost basis portion."""
        contracts = min(contracts, self.position)
        if contracts <= 0:
            return 0.0
        cost_portion = self.avg_price * contracts
        self.position -= contracts
        self.cost_basis = self.avg_price * self.position
        return cost_portion

    @property
    def is_risk_off(self) -> bool:
        return self.risk_off_until is not None

    def check_cooldown(self, now: datetime):
        """Clear cooldown if expired."""
        if self.risk_off_until and now >= self.risk_off_until:
            self.risk_off_until = None


@dataclass
class QuoteResult:
    """Output of quote calculation."""
    bid_price: Optional[float] = None
    bid_size: float = 0.0       # In contracts
    ask_price: Optional[float] = None
    ask_size: float = 0.0       # In contracts
    skip_reason: Optional[str] = None

    @property
    def spread(self) -> Optional[float]:
        if self.bid_price and self.ask_price:
            return self.ask_price - self.bid_price
        return None


class MarketMakingStrategy(BaseStrategy):
    """
    Market Making Strategy for Polymarket prediction markets.

    Places two-sided quotes around mid-price to capture spread.
    Uses poly-maker's risk management: stop-loss, take-profit, volatility guard.

    This class works in two modes:
    1. Standard mode: generate_signal()/should_exit() for the base BacktestEngine
    2. MM mode: calculate_quotes()/check_stop_loss() for MarketMakingEngine
    """

    def __init__(self, params: Optional[MarketMakingParams] = None, **kwargs):
        super().__init__(
            name="MarketMaking",
            max_position_size=0.05,
            max_positions=30,
            **kwargs
        )
        self.params = params or MarketMakingParams()

        # Per-market inventory
        self.inventory: Dict[str, InventoryState] = {}

        # Price history for volatility
        self.price_history: Dict[str, deque] = {}
        self._max_history = 50

        # Stats
        self.total_spread_captured: float = 0.0
        self.total_maker_rebates: float = 0.0
        self.total_volume_traded: float = 0.0
        self.trades_by_market: Dict[str, int] = {}

    # ---- Internal helpers ----

    def get_inventory(self, market_id: str) -> InventoryState:
        if market_id not in self.inventory:
            self.inventory[market_id] = InventoryState()
        return self.inventory[market_id]

    def update_price_history(self, market_id: str, price: float, ts: datetime):
        if market_id not in self.price_history:
            self.price_history[market_id] = deque(maxlen=self._max_history)
        self.price_history[market_id].append((ts, price))

    def estimate_volatility(self, market_id: str) -> float:
        """Rolling standard deviation of price returns."""
        history = self.price_history.get(market_id)
        if not history or len(history) < 3:
            return 0.0
        prices = [p for _, p in history]
        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                returns.append((prices[i] - prices[i - 1]) / prices[i - 1])
        if not returns:
            return 0.0
        mean_r = sum(returns) / len(returns)
        var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        return var ** 0.5

    def estimate_spread(self, market_data: Dict[str, Any]) -> float:
        """
        Estimate bid-ask spread from liquidity.
        Higher liquidity = tighter spread.
        """
        liquidity = market_data.get("liquidity", 0)
        volume_24h = market_data.get("volume_24h", 0)
        if liquidity <= 0:
            return 0.10
        base = max(0.005, 0.50 / math.sqrt(liquidity / 1000))
        if volume_24h > 50000:
            base *= 0.7
        elif volume_24h > 10000:
            base *= 0.85
        return min(base, 0.10)

    # ---- Core MM Logic ----

    def calculate_quotes(
        self,
        market_data: Dict[str, Any],
        timestamp: datetime,
    ) -> QuoteResult:
        """
        Calculate two-sided quotes for a market.

        Returns bid/ask prices and sizes, or skip_reason if not quoting.
        This is the main entry point for MarketMakingEngine.
        """
        market_id = market_data.get("market_id", "")
        yes_price = market_data.get("yes_price", 0.5)
        liquidity = market_data.get("liquidity", 0)
        volume_24h = market_data.get("volume_24h", 0)

        inv = self.get_inventory(market_id)
        inv.check_cooldown(timestamp)

        # Update price history
        self.update_price_history(market_id, yes_price, timestamp)

        # --- Filters ---
        if liquidity < self.params.min_liquidity:
            return QuoteResult(skip_reason="low_liquidity")
        if volume_24h < self.params.min_volume_24h:
            return QuoteResult(skip_reason="low_volume")
        if yes_price > self.params.max_price or yes_price < self.params.min_price:
            return QuoteResult(skip_reason="price_out_of_range")

        vol = self.estimate_volatility(market_id)
        if vol > self.params.volatility_threshold:
            return QuoteResult(skip_reason="high_volatility")

        if inv.is_risk_off:
            return QuoteResult(skip_reason="risk_off_cooldown")

        # --- Spread ---
        market_spread = self.estimate_spread(market_data)
        mid = yes_price

        half = max(market_spread / 2, self.params.tick_size * 2)
        bid = round(mid - half, 4)
        ask = round(mid + half, 4)

        # Ensure minimum profitable spread
        if ask - bid < self.params.min_spread:
            half_target = self.params.min_spread / 2
            bid = round(mid - half_target, 4)
            ask = round(mid + half_target, 4)

        # Inventory skew: if overweight, bias quotes to reduce exposure
        if inv.position > 0 and self.params.inventory_skew_factor > 0:
            max_contracts = self.params.max_size / mid if mid > 0 else 1
            fill_ratio = inv.position / max_contracts if max_contracts > 0 else 0
            skew = fill_ratio * self.params.inventory_skew_factor * market_spread
            bid -= skew   # Lower bid = less eager to buy
            ask -= skew   # Lower ask = more eager to sell
            bid = round(bid, 4)
            ask = round(ask, 4)

        # Clamp to valid range
        bid = max(self.params.min_price, min(bid, self.params.max_price))
        ask = max(self.params.min_price, min(ask, self.params.max_price))

        # Ensure bid < ask
        if bid >= ask:
            bid = round(mid - self.params.min_spread / 2, 4)
            ask = round(mid + self.params.min_spread / 2, 4)

        # --- Sizes ---
        max_contracts = self.params.max_size / bid if bid > 0 else 0
        trade_contracts = self.params.trade_size / bid if bid > 0 else 0

        # Bid size: buy if below max
        bid_size = 0.0
        if inv.position < max_contracts:
            remaining = max_contracts - inv.position
            bid_size = min(trade_contracts, remaining)

        # Ask size: sell if we have inventory
        ask_size = 0.0
        if inv.position > 0:
            ask_size = min(inv.position, trade_contracts)

        # Apply take-profit floor on ask price
        if inv.position > 0 and inv.avg_price > 0:
            tp_price = round(inv.avg_price * (1 + self.params.take_profit_pct / 100), 4)
            ask = max(ask, tp_price)

        # Min order size filter
        min_contracts = self.params.min_order_size / bid if bid > 0 else float("inf")
        if 0 < bid_size < min_contracts:
            bid_size = 0.0
        if 0 < ask_size < min_contracts:
            ask_size = 0.0

        return QuoteResult(
            bid_price=bid if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=ask if ask_size > 0 else None,
            ask_size=ask_size,
        )

    def check_stop_loss(
        self,
        market_data: Dict[str, Any],
        timestamp: datetime,
    ) -> bool:
        """
        Check if stop-loss should fire for this market.
        Returns True if position should be emergency-closed.
        """
        market_id = market_data.get("market_id", "")
        yes_price = market_data.get("yes_price", 0.5)
        inv = self.get_inventory(market_id)

        if inv.position <= 0 or inv.avg_price <= 0:
            return False

        pnl_pct = (yes_price - inv.avg_price) / inv.avg_price * 100
        vol = self.estimate_volatility(market_id)

        if pnl_pct < self.params.stop_loss_pct:
            inv.risk_off_until = timestamp + timedelta(hours=self.params.sleep_period_hours)
            return True

        if vol > self.params.volatility_threshold and pnl_pct < 0:
            inv.risk_off_until = timestamp + timedelta(hours=self.params.sleep_period_hours)
            return True

        return False

    # ---- BaseStrategy interface (for standard engine compatibility) ----

    def generate_signal(
        self,
        market_data: Dict[str, Any],
        historical_data: Optional[List[Dict]] = None,
    ) -> Signal:
        """
        Simplified signal for the standard BacktestEngine.
        For proper MM backtesting, use MarketMakingEngine instead.
        """
        market_id = market_data.get("market_id", "")
        yes_price = market_data.get("yes_price", 0.5)
        liquidity = market_data.get("liquidity", 0)
        volume_24h = market_data.get("volume_24h", 0)
        end_date = market_data.get("end_date")

        ts = datetime.now()
        self.update_price_history(market_id, yes_price, ts)

        if liquidity < self.params.min_liquidity:
            return Signal.HOLD
        if volume_24h < self.params.min_volume_24h:
            return Signal.HOLD
        if yes_price > self.params.max_price or yes_price < self.params.min_price:
            return Signal.HOLD

        spread = self.estimate_spread(market_data)
        if spread < self.params.min_spread:
            return Signal.HOLD

        vol = self.estimate_volatility(market_id)
        if vol > self.params.volatility_threshold:
            return Signal.HOLD

        inv = self.get_inventory(market_id)
        inv.check_cooldown(ts)
        if inv.is_risk_off:
            return Signal.HOLD

        max_contracts = self.params.max_size / yes_price if yes_price > 0 else 0
        if inv.position < max_contracts:
            return Signal.BUY

        return Signal.HOLD

    def should_exit(
        self,
        position: Position,
        market_data: Dict[str, Any],
    ) -> bool:
        """Exit conditions for standard engine compatibility."""
        if market_data.get("closed", False) or market_data.get("resolved", False):
            return True

        market_id = market_data.get("market_id", "")
        yes_price = market_data.get("yes_price", 0.5)
        inv = self.get_inventory(market_id)

        if inv.avg_price > 0:
            pnl_pct = (yes_price - inv.avg_price) / inv.avg_price * 100
            if pnl_pct < self.params.stop_loss_pct:
                return True
            if pnl_pct > self.params.take_profit_pct:
                return True

        vol = self.estimate_volatility(market_id)
        if vol > self.params.volatility_threshold:
            return True

        return False

    def get_mm_metrics(self) -> Dict[str, Any]:
        """Market-making specific performance metrics."""
        active_markets = sum(1 for inv in self.inventory.values() if inv.position > 0)
        total_inventory_value = sum(
            inv.position * inv.avg_price for inv in self.inventory.values()
        )
        return {
            "total_spread_captured": self.total_spread_captured,
            "total_maker_rebates": self.total_maker_rebates,
            "total_volume_traded": self.total_volume_traded,
            "active_markets": active_markets,
            "total_inventory_value": total_inventory_value,
            "markets_traded": len(self.trades_by_market),
        }
