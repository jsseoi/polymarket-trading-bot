"""
Market Making Backtest Engine

Extends BacktestEngine with limit order simulation for market-making strategies.

Key differences from the standard engine:
- Simulates two-sided limit order fills (bid + ask)
- Fill probability based on price movement between snapshots
- Polymarket-specific fee model: maker orders = 0% fee + rebate
- Tracks spread capture, inventory, and market-making specific metrics
"""

import math
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from .engine import BacktestEngine, BacktestConfig, BacktestResult, MarketSnapshot
from ..strategies.market_making import (
    MarketMakingStrategy,
    MarketMakingParams,
    QuoteResult,
    InventoryState,
    FeeConfig,
    FEE_POLITICAL,
)


@dataclass
class MMBacktestConfig(BacktestConfig):
    """Extended config for market-making backtests."""
    # Override base: maker orders have no commission
    commission: float = 0.0
    slippage: float = 0.0

    # Fill simulation
    fill_aggression: float = 0.5  # 0 = conservative, 1 = aggressive fill assumptions
    use_random_fills: bool = True  # Add randomness to fill simulation

    # Fee config (overrides strategy's if set)
    fee_config: Optional[FeeConfig] = None


@dataclass
class FillEvent:
    """Record of a simulated fill."""
    timestamp: datetime
    market_id: str
    side: str           # "BUY" or "SELL"
    price: float
    size: float         # Contracts
    fee: float          # Negative = rebate income
    spread_captured: float  # Spread earned on this fill (if closing)


@dataclass
class MMBacktestResult(BacktestResult):
    """Extended results with market-making metrics."""
    total_spread_captured: float = 0.0
    total_maker_rebates: float = 0.0
    total_volume: float = 0.0
    fill_rate: float = 0.0           # % of quotes that filled
    avg_spread_captured: float = 0.0
    markets_traded: int = 0
    avg_inventory_time_hours: float = 0.0
    fills: List[Dict[str, Any]] = field(default_factory=list)

    def mm_summary(self) -> str:
        """Market-making specific summary."""
        base = self.summary()
        return base + f"""
║  MARKET MAKING METRICS
║  ───────────────────────────────────────────────────────────
║  Total Spread Captured:  ${self.total_spread_captured:>10,.2f}
║  Total Maker Rebates:    ${self.total_maker_rebates:>10,.2f}
║  Total Volume Traded:    ${self.total_volume:>10,.2f}
║  Fill Rate:               {self.fill_rate:>10.1%}
║  Avg Spread per Fill:    ${self.avg_spread_captured:>10,.4f}
║  Markets Traded:          {self.markets_traded:>10}
╚══════════════════════════════════════════════════════════════╝
"""


class MarketMakingEngine(BacktestEngine):
    """
    Backtest engine specialized for market-making strategies.

    Simulates limit order placement and fill logic:
    - Strategy generates two-sided quotes (bid + ask) per snapshot
    - Engine determines if quotes would have filled based on price movement
    - Applies Polymarket maker fee model (no fee + rebate)
    - Tracks inventory, spread capture, and risk events

    Fill model:
    - Between consecutive snapshots at prices P1 -> P2:
      - Bid at Pb fills if: min(P1, P2) <= Pb (price dropped to our level)
      - Ask at Pa fills if: max(P1, P2) >= Pa (price rose to our level)
      - When prices are close, uses probabilistic fills based on volatility
    """

    def run_mm(
        self,
        strategy: MarketMakingStrategy,
        config: MMBacktestConfig,
    ) -> MMBacktestResult:
        """
        Run market-making backtest.

        Processes snapshots chronologically, simulating limit order
        placement and fills for each market the strategy quotes.
        """
        from ..strategies.base_strategy import StrategyState

        # Reset
        strategy.state = StrategyState(capital=config.initial_capital)
        strategy.inventory.clear()
        strategy.price_history.clear()
        strategy.total_spread_captured = 0.0
        strategy.total_maker_rebates = 0.0
        strategy.total_volume_traded = 0.0
        strategy.trades_by_market.clear()

        fee_config = config.fee_config or strategy.params.fee_config

        # Filter and sort snapshots
        snapshots = sorted(
            (s for s in self.all_snapshots
             if config.start_date <= s.timestamp <= config.end_date),
            key=lambda s: s.timestamp,
        )
        if not snapshots:
            raise ValueError("No data in specified date range")

        # Group by market for price-path tracking
        market_snapshots: Dict[str, List[MarketSnapshot]] = {}
        for snap in snapshots:
            market_snapshots.setdefault(snap.market_id, []).append(snap)

        # Track state
        equity_curve: List[Dict[str, Any]] = []
        peak_equity = config.initial_capital
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        exposure_periods = 0
        total_periods = 0

        all_fills: List[FillEvent] = []
        total_quotes = 0
        total_fills = 0

        # Group snapshots by date
        snapshots_by_date: Dict[Any, List[MarketSnapshot]] = {}
        for snap in snapshots:
            date_key = snap.timestamp.date()
            snapshots_by_date.setdefault(date_key, []).append(snap)

        # Previous prices for fill detection
        prev_prices: Dict[str, float] = {}

        for date_key in sorted(snapshots_by_date.keys()):
            day_snaps = snapshots_by_date[date_key]
            total_periods += 1

            # --- Phase 1: Check stop-losses and resolved markets ---
            for snap in day_snaps:
                market_id = snap.market_id
                inv = strategy.get_inventory(market_id)
                market_data = self._snapshot_to_dict(snap)

                # Handle resolved markets
                if snap.resolved and inv.position > 0:
                    exit_price = 1.0 if snap.resolution == "YES" else 0.0
                    pnl = (exit_price - inv.avg_price) * inv.position
                    strategy.state.capital += exit_price * inv.position
                    fill = FillEvent(
                        timestamp=snap.timestamp,
                        market_id=market_id,
                        side="SELL",
                        price=exit_price,
                        size=inv.position,
                        fee=0.0,
                        spread_captured=pnl,
                    )
                    all_fills.append(fill)
                    strategy.total_spread_captured += max(0, pnl)
                    inv.position = 0.0
                    inv.avg_price = 0.0
                    inv.cost_basis = 0.0
                    continue

                # Check stop-loss
                if strategy.check_stop_loss(market_data, snap.timestamp):
                    exit_price = snap.yes_price * (1 - 0.005)  # Small slippage on panic sell
                    pnl = (exit_price - inv.avg_price) * inv.position
                    strategy.state.capital += exit_price * inv.position
                    fill = FillEvent(
                        timestamp=snap.timestamp,
                        market_id=market_id,
                        side="SELL",
                        price=exit_price,
                        size=inv.position,
                        fee=fee_config.taker_fee(exit_price) * exit_price * inv.position,
                        spread_captured=pnl,
                    )
                    all_fills.append(fill)
                    strategy.state.capital -= fill.fee  # Stop-loss is taker
                    inv.position = 0.0
                    inv.avg_price = 0.0
                    inv.cost_basis = 0.0
                    total_fills += 1

            # --- Phase 2: Generate quotes and simulate fills ---
            for snap in day_snaps:
                market_id = snap.market_id
                market_data = self._snapshot_to_dict(snap)
                inv = strategy.get_inventory(market_id)

                if snap.resolved:
                    prev_prices[market_id] = snap.yes_price
                    continue

                quote = strategy.calculate_quotes(market_data, snap.timestamp)

                if quote.skip_reason:
                    prev_prices[market_id] = snap.yes_price
                    continue

                prev_price = prev_prices.get(market_id, snap.yes_price)
                curr_price = snap.yes_price

                # Estimate intra-period price range
                vol = strategy.estimate_volatility(market_id)
                noise = vol * 0.5  # Half-period volatility estimate
                period_low = min(prev_price, curr_price) - noise
                period_high = max(prev_price, curr_price) + noise

                # --- Simulate bid fill ---
                if quote.bid_price is not None and quote.bid_size > 0:
                    total_quotes += 1
                    cost = quote.bid_price * quote.bid_size

                    if cost <= strategy.state.capital:
                        filled = self._check_fill(
                            "BUY", quote.bid_price, period_low, period_high,
                            prev_price, curr_price, vol, config,
                        )
                        if filled:
                            # Maker fill: no fee + rebate
                            rebate = fee_config.maker_rebate(quote.bid_price) * cost
                            strategy.state.capital -= cost
                            strategy.state.capital += rebate
                            inv.add(quote.bid_size, quote.bid_price)
                            strategy.total_maker_rebates += rebate
                            strategy.total_volume_traded += cost
                            strategy.trades_by_market[market_id] = (
                                strategy.trades_by_market.get(market_id, 0) + 1
                            )

                            all_fills.append(FillEvent(
                                timestamp=snap.timestamp,
                                market_id=market_id,
                                side="BUY",
                                price=quote.bid_price,
                                size=quote.bid_size,
                                fee=-rebate,
                                spread_captured=0.0,
                            ))
                            total_fills += 1

                # --- Simulate ask fill ---
                if quote.ask_price is not None and quote.ask_size > 0 and inv.position > 0:
                    total_quotes += 1
                    sell_contracts = min(quote.ask_size, inv.position)
                    proceeds = quote.ask_price * sell_contracts

                    filled = self._check_fill(
                        "SELL", quote.ask_price, period_low, period_high,
                        prev_price, curr_price, vol, config,
                    )
                    if filled:
                        rebate = fee_config.maker_rebate(quote.ask_price) * proceeds
                        spread_earned = (quote.ask_price - inv.avg_price) * sell_contracts
                        strategy.state.capital += proceeds + rebate
                        inv.remove(sell_contracts)
                        strategy.total_maker_rebates += rebate
                        strategy.total_spread_captured += max(0, spread_earned)
                        strategy.total_volume_traded += proceeds

                        all_fills.append(FillEvent(
                            timestamp=snap.timestamp,
                            market_id=market_id,
                            side="SELL",
                            price=quote.ask_price,
                            size=sell_contracts,
                            fee=-rebate,
                            spread_captured=spread_earned,
                        ))
                        total_fills += 1

                prev_prices[market_id] = curr_price

            # --- Phase 3: Mark-to-market and track equity ---
            has_positions = False
            current_equity = strategy.state.capital
            for market_id, inv in strategy.inventory.items():
                if inv.position > 0:
                    has_positions = True
                    snaps_for_market = [
                        s for s in day_snaps if s.market_id == market_id
                    ]
                    if snaps_for_market:
                        mtm_price = snaps_for_market[-1].yes_price
                    else:
                        mtm_price = inv.avg_price
                    current_equity += mtm_price * inv.position

            if has_positions:
                exposure_periods += 1

            if current_equity > peak_equity:
                peak_equity = current_equity
            drawdown = peak_equity - current_equity
            drawdown_pct = drawdown / peak_equity if peak_equity > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct

            equity_curve.append({
                "date": str(date_key),
                "equity": current_equity,
                "drawdown": drawdown,
                "positions": sum(
                    1 for inv in strategy.inventory.values() if inv.position > 0
                ),
            })

        # --- Final: close remaining positions at last known price ---
        for market_id, inv in strategy.inventory.items():
            if inv.position > 0:
                if market_id in market_snapshots:
                    last_snap = market_snapshots[market_id][-1]
                    exit_price = last_snap.yes_price * (1 - 0.005)
                else:
                    exit_price = inv.avg_price
                strategy.state.capital += exit_price * inv.position
                inv.position = 0.0

        # --- Calculate result metrics ---
        sell_fills = [f for f in all_fills if f.side == "SELL"]
        buy_fills = [f for f in all_fills if f.side == "BUY"]

        total_return = strategy.state.capital - config.initial_capital
        total_return_pct = total_return / config.initial_capital if config.initial_capital > 0 else 0

        # Sharpe from daily equity returns
        sharpe_ratio = 0.0
        if len(equity_curve) > 2:
            equities = [e["equity"] for e in equity_curve]
            daily_returns = [
                (equities[i] - equities[i - 1]) / equities[i - 1]
                for i in range(1, len(equities))
                if equities[i - 1] > 0
            ]
            if daily_returns:
                avg_r = sum(daily_returns) / len(daily_returns)
                std_r = (sum((r - avg_r) ** 2 for r in daily_returns) / len(daily_returns)) ** 0.5
                sharpe_ratio = (avg_r / std_r * (252 ** 0.5)) if std_r > 0 else 0

        # Trade-level PnL from spread captures
        winning_fills = [f for f in sell_fills if f.spread_captured > 0]
        losing_fills = [f for f in sell_fills if f.spread_captured <= 0]

        gross_profit = sum(f.spread_captured for f in winning_fills)
        gross_loss = abs(sum(f.spread_captured for f in losing_fills))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        avg_spread = (
            strategy.total_spread_captured / len(sell_fills)
            if sell_fills
            else 0.0
        )

        return MMBacktestResult(
            strategy_name=strategy.name,
            config=config,
            final_capital=strategy.state.capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=len(all_fills),
            winning_trades=len(winning_fills),
            losing_trades=len(losing_fills),
            win_rate=len(winning_fills) / len(sell_fills) if sell_fills else 0,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            profit_factor=profit_factor,
            avg_trade_pnl=(
                sum(f.spread_captured for f in sell_fills) / len(sell_fills)
                if sell_fills else 0
            ),
            avg_win=(
                sum(f.spread_captured for f in winning_fills) / len(winning_fills)
                if winning_fills else 0
            ),
            avg_loss=(
                sum(f.spread_captured for f in losing_fills) / len(losing_fills)
                if losing_fills else 0
            ),
            best_trade=max((f.spread_captured for f in sell_fills), default=0),
            worst_trade=min((f.spread_captured for f in sell_fills), default=0),
            exposure_time_pct=(
                exposure_periods / total_periods if total_periods > 0 else 0
            ),
            equity_curve=equity_curve,
            trades=[{
                "timestamp": str(f.timestamp),
                "market_id": f.market_id,
                "side": f.side,
                "price": f.price,
                "size": f.size,
                "fee": f.fee,
                "spread_captured": f.spread_captured,
            } for f in all_fills],
            # MM-specific
            total_spread_captured=strategy.total_spread_captured,
            total_maker_rebates=strategy.total_maker_rebates,
            total_volume=strategy.total_volume_traded,
            fill_rate=total_fills / total_quotes if total_quotes > 0 else 0,
            avg_spread_captured=avg_spread,
            markets_traded=len(strategy.trades_by_market),
            fills=[{
                "timestamp": str(f.timestamp),
                "market_id": f.market_id,
                "side": f.side,
                "price": f.price,
                "size": f.size,
            } for f in all_fills],
        )

    def _check_fill(
        self,
        side: str,
        order_price: float,
        period_low: float,
        period_high: float,
        prev_price: float,
        curr_price: float,
        volatility: float,
        config: MMBacktestConfig,
    ) -> bool:
        """
        Determine if a limit order would have filled during this period.

        Fill logic:
        - BUY at Pb: fills if price dropped to Pb (period_low <= Pb)
        - SELL at Pa: fills if price rose to Pa (period_high >= Pa)
        - Probabilistic fills near the boundary based on volatility
        """
        if side == "BUY":
            # Definite fill: price clearly crossed our bid
            if min(prev_price, curr_price) <= order_price:
                return True
            # Probable fill: within volatility range
            if period_low <= order_price:
                distance = order_price - min(prev_price, curr_price)
                range_size = max(prev_price, curr_price) - period_low
                if range_size > 0:
                    prob = config.fill_aggression * (1 - abs(distance) / range_size)
                    prob = max(0.05, min(prob, 0.8))
                else:
                    prob = 0.1
                if config.use_random_fills:
                    return random.random() < prob
                return prob > 0.5
            return False

        else:  # SELL
            if max(prev_price, curr_price) >= order_price:
                return True
            if period_high >= order_price:
                distance = max(prev_price, curr_price) - order_price
                range_size = period_high - min(prev_price, curr_price)
                if range_size > 0:
                    prob = config.fill_aggression * (1 - abs(distance) / range_size)
                    prob = max(0.05, min(prob, 0.8))
                else:
                    prob = 0.1
                if config.use_random_fills:
                    return random.random() < prob
                return prob > 0.5
            return False

    def generate_mm_synthetic_data(
        self,
        num_markets: int = 30,
        days: int = 90,
        snapshots_per_day: int = 4,
        seed: Optional[int] = None,
    ) -> int:
        """
        Generate synthetic data optimized for market-making backtests.

        Creates markets with varying liquidity profiles:
        - High liquidity (40%): $100K-$500K, tight spreads
        - Medium liquidity (40%): $10K-$100K
        - Low liquidity (20%): $1K-$10K
        """
        if seed is not None:
            random.seed(seed)

        start_date = datetime.now() - timedelta(days=days)

        for i in range(num_markets):
            market_id = f"mm_synthetic_{i:04d}"

            # Liquidity tier
            tier = random.random()
            if tier < 0.4:
                base_liquidity = random.uniform(100_000, 500_000)
                base_volume = base_liquidity * random.uniform(0.5, 2.0)
            elif tier < 0.8:
                base_liquidity = random.uniform(10_000, 100_000)
                base_volume = base_liquidity * random.uniform(0.3, 1.5)
            else:
                base_liquidity = random.uniform(1_000, 10_000)
                base_volume = base_liquidity * random.uniform(0.1, 0.8)

            initial_price = random.uniform(0.15, 0.85)
            volatility = random.uniform(0.005, 0.03)
            duration_days = random.randint(14, min(80, days))
            end_date = start_date + timedelta(days=random.randint(duration_days, days))
            resolution = "YES" if random.random() < initial_price else "NO"

            price = initial_price

            for day in range(duration_days):
                current_date = start_date + timedelta(days=day)

                # Daily liquidity variation
                daily_liq = base_liquidity * random.uniform(0.7, 1.3)
                daily_vol = base_volume / 30 * random.uniform(0.3, 3.0)

                for snap_idx in range(snapshots_per_day):
                    timestamp = current_date + timedelta(hours=snap_idx * (24 // snapshots_per_day))

                    # Mean-reverting random walk
                    drift = (initial_price - price) * 0.05
                    shock = random.gauss(0, volatility)
                    price = max(0.02, min(0.98, price + drift + shock))

                    # Near resolution: converge to outcome
                    days_to_end = (end_date - timestamp).days
                    if days_to_end < 5:
                        target = 0.98 if resolution == "YES" else 0.02
                        alpha = max(0.1, 1 - days_to_end / 5)
                        price = price + (target - price) * alpha * 0.3

                    resolved = timestamp >= end_date

                    snapshot = MarketSnapshot(
                        timestamp=timestamp,
                        market_id=market_id,
                        question=f"MM Synthetic {i}: Event outcome?",
                        yes_price=round(price, 4),
                        no_price=round(1 - price, 4),
                        volume=round(daily_vol * 30 * random.uniform(0.8, 1.2), 2),
                        volume_24h=round(daily_vol * random.uniform(0.5, 2.0), 2),
                        liquidity=round(daily_liq, 2),
                        end_date=end_date,
                        resolved=resolved,
                        resolution=resolution if resolved else None,
                    )

                    self.all_snapshots.append(snapshot)
                    self.market_data.setdefault(market_id, []).append(snapshot)

        self.all_snapshots.sort(key=lambda x: x.timestamp)
        for mid in self.market_data:
            self.market_data[mid].sort(key=lambda x: x.timestamp)

        return len(self.all_snapshots)
