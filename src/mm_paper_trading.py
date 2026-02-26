#!/usr/bin/env python3
"""
Market Making Paper Trader

Automated paper trading for market-making on Polymarket.
Runs a continuous loop that:
1. Discovers suitable markets via Gamma API
2. Fetches real-time orderbooks via CLOB API
3. Generates two-sided quotes using MarketMakingStrategy
4. Simulates limit order placement and fill detection
5. Tracks P&L, positions, and risk metrics

Usage:
    python -m src.mm_paper_trading start          # Start automated MM
    python -m src.mm_paper_trading start --capital 500  # Custom capital
    python -m src.mm_paper_trading status          # Check current state
    python -m src.mm_paper_trading reset           # Reset portfolio
    python -m src.mm_paper_trading markets         # Show tracked markets
"""

import argparse
import json
import time
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any

from .api.gamma_client import GammaClient
from .api.clob_client import ClobClient, Side
from .strategies.market_making import (
    MarketMakingStrategy,
    MarketMakingParams,
    FeeConfig,
    FEE_POLITICAL,
    QuoteResult,
    InventoryState,
)


# --- State ---

@dataclass
class PendingOrder:
    """A simulated limit order waiting to fill."""
    order_id: str
    market_id: str
    token_id: str
    question: str
    side: str       # "BUY" or "SELL"
    price: float
    size: float     # contracts
    placed_at: str
    expires_at: str  # cancel after this time

    def is_expired(self, now: datetime) -> bool:
        return now >= datetime.fromisoformat(self.expires_at)


@dataclass
class MMPosition:
    """An open market-making position."""
    market_id: str
    token_id: str
    question: str
    side: str  # always "YES" for simplicity
    contracts: float
    avg_price: float
    cost_basis: float
    entry_time: str
    current_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class MMTrade:
    """A completed round-trip or partial fill."""
    trade_id: str
    market_id: str
    question: str
    side: str       # "BUY" or "SELL"
    price: float
    size: float
    fee: float
    pnl: float      # realized P&L for sells
    timestamp: str
    spread_captured: float = 0.0


@dataclass
class MMPortfolio:
    """Market-making paper trading portfolio."""
    cash: float = 1000.0
    initial_cash: float = 1000.0
    positions: Dict[str, MMPosition] = field(default_factory=dict)
    pending_orders: List[PendingOrder] = field(default_factory=list)
    trades: List[MMTrade] = field(default_factory=list)
    total_spread_captured: float = 0.0
    total_adverse_selection_est: float = 0.0
    total_volume: float = 0.0
    total_rebates: float = 0.0
    quotes_placed: int = 0
    quotes_filled: int = 0
    created_at: str = ""
    updated_at: str = ""
    ticks: int = 0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()


@dataclass
class TrackedMarket:
    """A market being actively tracked for MM opportunities."""
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    category: Optional[str]
    end_date: Optional[str]
    last_yes_price: float = 0.5
    last_spread: float = 0.0
    last_volume_24h: float = 0.0
    last_liquidity: float = 0.0
    last_updated: str = ""


class MMPaperTrader:
    """
    Automated market-making paper trader for Polymarket.

    Runs a loop that discovers markets, generates quotes, and
    simulates fills using real-time price data.
    """

    STATE_FILE = Path("data/mm_paper_state.json")
    PARAMS_FILE = Path("data/optimized_params_v2.json")

    def __init__(
        self,
        initial_capital: float = 1000.0,
        tick_interval: float = 300.0,   # seconds between ticks
        market_refresh: float = 3600.0, # seconds between market rediscovery
        order_ttl: float = 600.0,       # seconds before pending orders expire
        max_markets: int = 10,
        params: Optional[MarketMakingParams] = None,
    ):
        self.gamma = GammaClient()
        self.clob = ClobClient()
        self.initial_capital = initial_capital
        self.tick_interval = tick_interval
        self.market_refresh = market_refresh
        self.order_ttl = order_ttl
        self.max_markets = max_markets
        self._running = False
        self._order_counter = 0
        self._last_market_refresh = datetime.min

        # Load optimized params or use provided
        if params:
            self.params = params
        else:
            self.params = self._load_optimized_params()

        self.strategy = MarketMakingStrategy(self.params)
        self.portfolio = self._load_state()
        self.tracked_markets: Dict[str, TrackedMarket] = {}

    def _load_optimized_params(self) -> MarketMakingParams:
        """Load optimized parameters from file."""
        if self.PARAMS_FILE.exists():
            with open(self.PARAMS_FILE) as f:
                data = json.load(f)
            p = data.get("optimized_params", {})
            return MarketMakingParams(
                min_spread=p.get("min_spread", 0.046),
                trade_size=p.get("trade_size", 29.0),
                max_size=p.get("max_size", 307.0),
                stop_loss_pct=p.get("stop_loss_pct", -9.0),
                take_profit_pct=p.get("take_profit_pct", 3.0),
                volatility_threshold=p.get("volatility_threshold", 0.036),
                inventory_skew_factor=p.get("inventory_skew_factor", 0.97),
                sleep_period_hours=p.get("sleep_period_hours", 0.62),
                fee_config=FEE_POLITICAL,
            )
        return MarketMakingParams()

    # --- State Persistence ---

    def _load_state(self) -> MMPortfolio:
        if self.STATE_FILE.exists():
            with open(self.STATE_FILE) as f:
                data = json.load(f)
            positions = {}
            for mid, p in data.get("positions", {}).items():
                positions[mid] = MMPosition(**p)
            orders = [PendingOrder(**o) for o in data.get("pending_orders", [])]
            trades = [MMTrade(**t) for t in data.get("trades", [])]
            return MMPortfolio(
                cash=data.get("cash", self.initial_capital),
                initial_cash=data.get("initial_cash", self.initial_capital),
                positions=positions,
                pending_orders=orders,
                trades=trades,
                total_spread_captured=data.get("total_spread_captured", 0),
                total_adverse_selection_est=data.get("total_adverse_selection_est", 0),
                total_volume=data.get("total_volume", 0),
                total_rebates=data.get("total_rebates", 0),
                quotes_placed=data.get("quotes_placed", 0),
                quotes_filled=data.get("quotes_filled", 0),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                ticks=data.get("ticks", 0),
            )
        return MMPortfolio(cash=self.initial_capital, initial_cash=self.initial_capital)

    def _save_state(self):
        self.portfolio.updated_at = datetime.now().isoformat()
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cash": self.portfolio.cash,
            "initial_cash": self.portfolio.initial_cash,
            "positions": {mid: asdict(p) for mid, p in self.portfolio.positions.items()},
            "pending_orders": [asdict(o) for o in self.portfolio.pending_orders],
            "trades": [asdict(t) for t in self.portfolio.trades[-500:]],  # Keep last 500
            "total_spread_captured": self.portfolio.total_spread_captured,
            "total_adverse_selection_est": self.portfolio.total_adverse_selection_est,
            "total_volume": self.portfolio.total_volume,
            "total_rebates": self.portfolio.total_rebates,
            "quotes_placed": self.portfolio.quotes_placed,
            "quotes_filled": self.portfolio.quotes_filled,
            "created_at": self.portfolio.created_at,
            "updated_at": self.portfolio.updated_at,
            "ticks": self.portfolio.ticks,
        }
        with open(self.STATE_FILE, 'w') as f:
            json.dump(data, f, indent=2)

    def _gen_order_id(self) -> str:
        self._order_counter += 1
        return f"mm_{int(time.time())}_{self._order_counter}"

    # --- Market Discovery ---

    def discover_markets(self):
        """Find markets suitable for market-making using Gamma API."""
        now = datetime.now()
        if (now - self._last_market_refresh).total_seconds() < self.market_refresh:
            return  # Not time to refresh yet

        print(f"\n[{now.strftime('%H:%M:%S')}] Discovering markets...")
        try:
            raw_markets = self.gamma.get_markets(
                active=True, closed=False, limit=100, order="volume"
            )
        except Exception as e:
            print(f"  Error fetching markets: {e}")
            return

        candidates = []
        for m in raw_markets:
            # Apply MM filters
            if m.closed or not m.active:
                continue
            if m.liquidity < self.params.min_liquidity:
                continue

            # Price range filter
            if m.outcome_prices:
                yes_price = m.outcome_prices[0]
                if yes_price < self.params.min_price or yes_price > self.params.max_price:
                    continue
            else:
                continue

            # Expiry filter
            if m.end_date:
                days_to_expiry = (m.end_date.replace(tzinfo=None) - now).days
                if days_to_expiry < 7:
                    continue

            candidates.append(m)

        # Sort by volume descending, take top N
        candidates.sort(key=lambda m: m.volume, reverse=True)
        selected = candidates[:self.max_markets]

        # Try to get token IDs via CLOB for each market
        new_tracked = {}
        for m in selected:
            # Use existing token IDs if we already have them
            if m.condition_id in self.tracked_markets:
                existing = self.tracked_markets[m.condition_id]
                existing.last_yes_price = m.outcome_prices[0] if m.outcome_prices else 0.5
                existing.last_liquidity = m.liquidity
                existing.last_updated = now.isoformat()
                new_tracked[m.condition_id] = existing
            else:
                # For new markets, we need token IDs
                # The Gamma API Market doesn't directly expose token IDs
                # We'll use the condition_id as a proxy and attempt to
                # get the orderbook later when we have the token ID
                new_tracked[m.condition_id] = TrackedMarket(
                    condition_id=m.condition_id,
                    question=m.question,
                    yes_token_id="",  # Will be populated if available
                    no_token_id="",
                    category=m.category,
                    end_date=m.end_date.isoformat() if m.end_date else None,
                    last_yes_price=m.outcome_prices[0] if m.outcome_prices else 0.5,
                    last_liquidity=m.liquidity,
                    last_updated=now.isoformat(),
                )

        self.tracked_markets = new_tracked
        self._last_market_refresh = now
        print(f"  Tracking {len(self.tracked_markets)} markets")
        for mid, tm in list(self.tracked_markets.items())[:5]:
            print(f"    {tm.last_yes_price:.0%} | ${tm.last_liquidity:>10,.0f} | {tm.question[:50]}...")

    # --- Price Fetching ---

    def _fetch_market_data(self, tm: TrackedMarket) -> Optional[Dict[str, Any]]:
        """Fetch live price data for a tracked market."""
        try:
            market = self.gamma.get_market(tm.condition_id)
            if not market or not market.outcome_prices:
                return None

            yes_price = market.outcome_prices[0]
            no_price = market.outcome_prices[1] if len(market.outcome_prices) > 1 else 1 - yes_price

            # Try to get spread from CLOB if we have token ID
            spread = None
            if tm.yes_token_id:
                try:
                    spread = self.clob.get_spread(tm.yes_token_id)
                except Exception:
                    pass

            return {
                "market_id": tm.condition_id,
                "question": tm.question,
                "yes_price": yes_price,
                "no_price": no_price,
                "volume": market.volume,
                "volume_24h": market.volume,  # Gamma doesn't separate 24h
                "liquidity": market.liquidity,
                "end_date": tm.end_date,
                "closed": market.closed,
                "resolved": market.closed,
                "spread": spread,
            }
        except Exception as e:
            print(f"  Error fetching {tm.question[:30]}...: {e}")
            return None

    # --- Order Simulation ---

    def _process_pending_orders(self):
        """Check pending orders against current prices for fills."""
        now = datetime.now()
        remaining = []

        for order in self.portfolio.pending_orders:
            if order.is_expired(now):
                continue  # Drop expired orders

            tm = self.tracked_markets.get(order.market_id)
            if not tm:
                continue

            current_price = tm.last_yes_price
            filled = False

            if order.side == "BUY":
                # Bid fills if current price drops to or below bid
                if current_price <= order.price:
                    filled = True
            else:
                # Ask fills if current price rises to or above ask
                if current_price >= order.price:
                    filled = True

            if filled:
                self._execute_fill(order, current_price, now)
            else:
                remaining.append(order)

        self.portfolio.pending_orders = remaining

    def _execute_fill(self, order: PendingOrder, fill_price: float, now: datetime):
        """Execute a simulated fill."""
        self.portfolio.quotes_filled += 1
        cost = order.price * order.size
        fee_config = self.params.fee_config

        if order.side == "BUY":
            if cost > self.portfolio.cash:
                return  # Can't afford

            rebate = fee_config.maker_rebate(order.price) * cost
            self.portfolio.cash -= cost
            self.portfolio.cash += rebate
            self.portfolio.total_rebates += rebate
            self.portfolio.total_volume += cost

            # Update or create position
            pos = self.portfolio.positions.get(order.market_id)
            if pos:
                # Update average price
                total_cost = pos.cost_basis + cost
                total_contracts = pos.contracts + order.size
                pos.avg_price = total_cost / total_contracts if total_contracts > 0 else 0
                pos.contracts = total_contracts
                pos.cost_basis = total_cost
            else:
                self.portfolio.positions[order.market_id] = MMPosition(
                    market_id=order.market_id,
                    token_id=order.token_id,
                    question=order.question,
                    side="YES",
                    contracts=order.size,
                    avg_price=order.price,
                    cost_basis=cost,
                    entry_time=now.isoformat(),
                )

            # Also update strategy inventory for quote calculations
            inv = self.strategy.get_inventory(order.market_id)
            inv.add(order.size, order.price)

            self.portfolio.trades.append(MMTrade(
                trade_id=order.order_id,
                market_id=order.market_id,
                question=order.question,
                side="BUY",
                price=order.price,
                size=order.size,
                fee=-rebate,
                pnl=0.0,
                timestamp=now.isoformat(),
            ))

            print(f"  FILL BUY  {order.size:.1f}@{order.price:.4f} | {order.question[:40]}...")

        else:  # SELL
            pos = self.portfolio.positions.get(order.market_id)
            if not pos or pos.contracts <= 0:
                return

            sell_contracts = min(order.size, pos.contracts)
            proceeds = order.price * sell_contracts
            rebate = fee_config.maker_rebate(order.price) * proceeds
            spread_earned = (order.price - pos.avg_price) * sell_contracts

            self.portfolio.cash += proceeds + rebate
            self.portfolio.total_rebates += rebate
            self.portfolio.total_volume += proceeds
            self.portfolio.total_spread_captured += max(0, spread_earned)

            pos.contracts -= sell_contracts
            pos.cost_basis = pos.avg_price * pos.contracts
            if pos.contracts <= 0:
                del self.portfolio.positions[order.market_id]

            # Update strategy inventory
            inv = self.strategy.get_inventory(order.market_id)
            inv.remove(sell_contracts)

            self.portfolio.trades.append(MMTrade(
                trade_id=order.order_id,
                market_id=order.market_id,
                question=order.question,
                side="SELL",
                price=order.price,
                size=sell_contracts,
                fee=-rebate,
                pnl=spread_earned,
                timestamp=now.isoformat(),
                spread_captured=spread_earned,
            ))

            pnl_sym = "+" if spread_earned >= 0 else ""
            print(f"  FILL SELL {sell_contracts:.1f}@{order.price:.4f} "
                  f"P&L: {pnl_sym}${spread_earned:.2f} | {order.question[:40]}...")

    # --- Main Loop ---

    def _tick(self):
        """One iteration of the MM loop."""
        now = datetime.now()
        self.portfolio.ticks += 1

        # Refresh market list if needed
        self.discover_markets()

        # Process existing pending orders
        self._process_pending_orders()

        # Generate new quotes for each market
        markets_quoted = 0
        for mid, tm in self.tracked_markets.items():
            data = self._fetch_market_data(tm)
            if not data:
                continue

            # Update tracked market state
            tm.last_yes_price = data["yes_price"]
            tm.last_liquidity = data.get("liquidity", 0)
            tm.last_volume_24h = data.get("volume_24h", 0)
            tm.last_updated = now.isoformat()

            # Check stop-loss for existing positions
            if mid in self.portfolio.positions:
                if self.strategy.check_stop_loss(data, now):
                    pos = self.portfolio.positions[mid]
                    # Emergency close at current price with slippage
                    exit_price = data["yes_price"] * 0.995
                    proceeds = exit_price * pos.contracts
                    pnl = (exit_price - pos.avg_price) * pos.contracts
                    self.portfolio.cash += proceeds
                    del self.portfolio.positions[mid]

                    inv = self.strategy.get_inventory(mid)
                    inv.position = 0.0
                    inv.avg_price = 0.0

                    self.portfolio.trades.append(MMTrade(
                        trade_id=self._gen_order_id(),
                        market_id=mid,
                        question=tm.question,
                        side="STOP_LOSS",
                        price=exit_price,
                        size=pos.contracts,
                        fee=self.params.fee_config.taker_fee(exit_price) * proceeds,
                        pnl=pnl,
                        timestamp=now.isoformat(),
                    ))
                    print(f"  STOP-LOSS {pos.contracts:.1f}@{exit_price:.4f} "
                          f"P&L: ${pnl:+.2f} | {tm.question[:40]}...")
                    continue

            # Generate quotes
            quote = self.strategy.calculate_quotes(data, now)

            if quote.skip_reason:
                continue

            markets_quoted += 1
            expires = (now + timedelta(seconds=self.order_ttl)).isoformat()

            # Cancel existing orders for this market
            self.portfolio.pending_orders = [
                o for o in self.portfolio.pending_orders if o.market_id != mid
            ]

            # Place bid
            if quote.bid_price is not None and quote.bid_size > 0:
                cost = quote.bid_price * quote.bid_size
                if cost <= self.portfolio.cash:
                    self.portfolio.pending_orders.append(PendingOrder(
                        order_id=self._gen_order_id(),
                        market_id=mid,
                        token_id=tm.yes_token_id,
                        question=tm.question,
                        side="BUY",
                        price=quote.bid_price,
                        size=quote.bid_size,
                        placed_at=now.isoformat(),
                        expires_at=expires,
                    ))
                    self.portfolio.quotes_placed += 1

            # Place ask
            if quote.ask_price is not None and quote.ask_size > 0:
                self.portfolio.pending_orders.append(PendingOrder(
                    order_id=self._gen_order_id(),
                    market_id=mid,
                    token_id=tm.yes_token_id,
                    question=tm.question,
                    side="SELL",
                    price=quote.ask_price,
                    size=quote.ask_size,
                    placed_at=now.isoformat(),
                    expires_at=expires,
                ))
                self.portfolio.quotes_placed += 1

            # Rate limit: small delay between API calls
            time.sleep(0.2)

        # Update position mark-to-market
        self._mark_to_market()

        # Save state
        self._save_state()

        # Print tick summary
        total_equity = self._total_equity()
        total_pnl = total_equity - self.portfolio.initial_cash
        n_positions = len(self.portfolio.positions)
        n_orders = len(self.portfolio.pending_orders)
        fill_rate = (self.portfolio.quotes_filled / self.portfolio.quotes_placed * 100
                     if self.portfolio.quotes_placed > 0 else 0)

        print(f"\n[{now.strftime('%H:%M:%S')}] Tick #{self.portfolio.ticks} | "
              f"Equity: ${total_equity:,.2f} ({total_pnl:+.2f}) | "
              f"Positions: {n_positions} | Orders: {n_orders} | "
              f"Quoted: {markets_quoted} mkts | Fill rate: {fill_rate:.1f}%")

    def _mark_to_market(self):
        """Update all position values with current prices."""
        for mid, pos in self.portfolio.positions.items():
            tm = self.tracked_markets.get(mid)
            if tm:
                pos.current_price = tm.last_yes_price
                pos.unrealized_pnl = (pos.current_price - pos.avg_price) * pos.contracts

    def _total_equity(self) -> float:
        """Total portfolio value: cash + position values."""
        position_value = sum(
            pos.current_price * pos.contracts
            for pos in self.portfolio.positions.values()
        )
        return self.portfolio.cash + position_value

    # --- Public Interface ---

    def start(self):
        """Start the automated market-making loop."""
        print("=" * 60)
        print("  MARKET MAKING PAPER TRADER")
        print("=" * 60)
        print(f"  Capital:     ${self.portfolio.cash:,.2f}")
        print(f"  Tick:        {self.tick_interval:.0f}s")
        print(f"  Max Markets: {self.max_markets}")
        print(f"  Min Spread:  {self.params.min_spread:.1%}")
        print(f"  Trade Size:  ${self.params.trade_size:.0f}")
        print(f"  Max Size:    ${self.params.max_size:.0f}")
        print(f"  Stop Loss:   {self.params.stop_loss_pct:.1f}%")
        print(f"  Take Profit: {self.params.take_profit_pct:.1f}%")
        print(f"  Inv Skew:    {self.params.inventory_skew_factor:.2f}")
        print("=" * 60)
        print("  Press Ctrl+C to stop\n")

        self._running = True

        def handle_signal(sig, frame):
            print("\n\nShutting down gracefully...")
            self._running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        while self._running:
            try:
                self._tick()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\n  ERROR in tick: {e}")
                import traceback
                traceback.print_exc()

            if self._running:
                # Interruptible sleep
                for _ in range(int(self.tick_interval)):
                    if not self._running:
                        break
                    time.sleep(1)

        self._save_state()
        print("\nFinal state saved. Use 'status' to check portfolio.")

    def status(self):
        """Print portfolio status."""
        self._mark_to_market()

        total_equity = self._total_equity()
        total_pnl = total_equity - self.portfolio.initial_cash
        total_pnl_pct = total_pnl / self.portfolio.initial_cash if self.portfolio.initial_cash > 0 else 0

        sell_trades = [t for t in self.portfolio.trades if t.side == "SELL"]
        wins = sum(1 for t in sell_trades if t.pnl > 0)
        win_rate = wins / len(sell_trades) if sell_trades else 0
        fill_rate = (self.portfolio.quotes_filled / self.portfolio.quotes_placed
                     if self.portfolio.quotes_placed > 0 else 0)

        uptime = ""
        if self.portfolio.created_at:
            start = datetime.fromisoformat(self.portfolio.created_at)
            hours = (datetime.now() - start).total_seconds() / 3600
            uptime = f"{hours:.1f}h"

        print(f"""
{"=" * 66}
  MM PAPER TRADING PORTFOLIO
{"=" * 66}
  Cash:                ${self.portfolio.cash:>12,.2f}
  Position Value:      ${total_equity - self.portfolio.cash:>12,.2f}
  -----------------------------------------------------------
  Total Equity:        ${total_equity:>12,.2f}
  Total P&L:           ${total_pnl:>+12,.2f} ({total_pnl_pct:+.1%})
  -----------------------------------------------------------
  Spread Captured:     ${self.portfolio.total_spread_captured:>12,.2f}
  Maker Rebates:       ${self.portfolio.total_rebates:>12,.2f}
  Volume Traded:       ${self.portfolio.total_volume:>12,.2f}
  -----------------------------------------------------------
  Quotes Placed:        {self.portfolio.quotes_placed:>12}
  Quotes Filled:        {self.portfolio.quotes_filled:>12}
  Fill Rate:            {fill_rate:>12.1%}
  Round Trips:          {len(sell_trades):>12}
  Win Rate:             {win_rate:>12.1%}
  -----------------------------------------------------------
  Ticks:                {self.portfolio.ticks:>12}
  Uptime:               {uptime:>12}
  Pending Orders:       {len(self.portfolio.pending_orders):>12}
{"=" * 66}""")

        if self.portfolio.positions:
            print("\n  OPEN POSITIONS")
            print("  " + "-" * 60)
            for mid, pos in self.portfolio.positions.items():
                pnl_sym = "+" if pos.unrealized_pnl >= 0 else ""
                print(f"  {pos.contracts:>6.1f} @ {pos.avg_price:.4f} "
                      f"-> {pos.current_price:.4f} "
                      f"P&L: {pnl_sym}${pos.unrealized_pnl:.2f} "
                      f"| {pos.question[:35]}...")

        if self.portfolio.trades:
            recent = self.portfolio.trades[-10:]
            print(f"\n  RECENT TRADES (last {len(recent)})")
            print("  " + "-" * 60)
            for t in reversed(recent):
                ts = t.timestamp[11:19] if len(t.timestamp) > 19 else t.timestamp
                pnl_str = f"${t.pnl:+.2f}" if t.side != "BUY" else ""
                print(f"  {ts} {t.side:>5} {t.size:>6.1f}@{t.price:.4f} "
                      f"{pnl_str:>8} | {t.question[:30]}...")

        print()

    def show_markets(self):
        """Show currently tracked markets."""
        if not self.tracked_markets:
            print("No markets tracked. Run 'start' to discover markets.")
            return

        print(f"\n  Tracked Markets ({len(self.tracked_markets)})")
        print("  " + "-" * 60)
        for mid, tm in self.tracked_markets.items():
            has_pos = mid in self.portfolio.positions
            pos_str = " [POS]" if has_pos else ""
            print(f"  {tm.last_yes_price:>5.0%} | ${tm.last_liquidity:>10,.0f} | "
                  f"{tm.question[:45]}...{pos_str}")
        print()

    def reset(self, capital: float = 1000.0):
        """Reset portfolio."""
        self.portfolio = MMPortfolio(cash=capital, initial_cash=capital)
        self.strategy = MarketMakingStrategy(self.params)
        self.tracked_markets.clear()
        self._save_state()
        print(f"Portfolio reset with ${capital:,.2f}")


def main():
    parser = argparse.ArgumentParser(description="MM Paper Trading")
    subparsers = parser.add_subparsers(dest="command")

    p_start = subparsers.add_parser("start", help="Start automated MM")
    p_start.add_argument("--capital", type=float, default=1000.0, help="Initial capital")
    p_start.add_argument("--tick", type=float, default=300.0, help="Seconds between ticks")
    p_start.add_argument("--markets", type=int, default=10, help="Max markets to track")

    subparsers.add_parser("status", help="Show portfolio status")
    subparsers.add_parser("markets", help="Show tracked markets")

    p_reset = subparsers.add_parser("reset", help="Reset portfolio")
    p_reset.add_argument("--capital", type=float, default=1000.0, help="Initial capital")

    args = parser.parse_args()

    if args.command == "start":
        trader = MMPaperTrader(
            initial_capital=args.capital,
            tick_interval=args.tick,
            max_markets=args.markets,
        )
        trader.start()
    elif args.command == "status":
        trader = MMPaperTrader()
        trader.status()
    elif args.command == "markets":
        trader = MMPaperTrader()
        # Quick market discovery for display
        trader.discover_markets()
        trader.show_markets()
    elif args.command == "reset":
        trader = MMPaperTrader()
        trader.reset(args.capital)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
