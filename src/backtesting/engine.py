"""
Backtesting Engine

Simulates strategy performance against historical market data.
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Type
from dataclasses import dataclass, field
from pathlib import Path

from ..strategies.base_strategy import BaseStrategy, Signal, StrategyState


@dataclass
class MarketSnapshot:
    """Point-in-time market state."""
    timestamp: datetime
    market_id: str
    question: str
    yes_price: float
    no_price: float
    volume: float
    volume_24h: float
    liquidity: float
    end_date: Optional[datetime] = None
    resolved: bool = False
    resolution: Optional[str] = None  # "YES", "NO", or None


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    start_date: datetime
    end_date: datetime
    initial_capital: float = 10000.0
    commission: float = 0.02  # 2% fee
    slippage: float = 0.005  # 0.5% slippage estimate
    max_position_pct: float = 0.1  # Max 10% of capital per position
    rebalance_frequency: str = "daily"  # daily, hourly


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    strategy_name: str
    config: BacktestConfig
    final_capital: float
    total_return: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    best_trade: float
    worst_trade: float
    exposure_time_pct: float
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        return f"""
╔══════════════════════════════════════════════════════════════╗
║  BACKTEST RESULTS: {self.strategy_name:^40} ║
╠══════════════════════════════════════════════════════════════╣
║  Period: {self.config.start_date.date()} to {self.config.end_date.date()}
║  Initial Capital: ${self.config.initial_capital:,.2f}
╠══════════════════════════════════════════════════════════════╣
║  PERFORMANCE
║  ───────────────────────────────────────────────────────────
║  Final Capital:     ${self.final_capital:>12,.2f}
║  Total Return:      ${self.total_return:>12,.2f} ({self.total_return_pct:>6.1%})
║  Max Drawdown:      ${self.max_drawdown:>12,.2f} ({self.max_drawdown_pct:>6.1%})
║  Sharpe Ratio:       {self.sharpe_ratio:>12.2f}
╠══════════════════════════════════════════════════════════════╣
║  TRADES
║  ───────────────────────────────────────────────────────────
║  Total Trades:       {self.total_trades:>12}
║  Win Rate:           {self.win_rate:>12.1%}
║  Profit Factor:      {self.profit_factor:>12.2f}
║  Avg Trade P&L:     ${self.avg_trade_pnl:>12,.2f}
║  Avg Win:           ${self.avg_win:>12,.2f}
║  Avg Loss:          ${self.avg_loss:>12,.2f}
║  Best Trade:        ${self.best_trade:>12,.2f}
║  Worst Trade:       ${self.worst_trade:>12,.2f}
╠══════════════════════════════════════════════════════════════╣
║  Exposure Time:      {self.exposure_time_pct:>12.1%}
╚══════════════════════════════════════════════════════════════╝
"""


class BacktestEngine:
    """
    Runs backtests against historical market data.
    
    Usage:
        engine = BacktestEngine()
        engine.load_data("data/historical_markets.json")
        
        strategy = LongshotBiasStrategy()
        result = engine.run(strategy, config)
        
        print(result.summary())
    """
    
    def __init__(self):
        self.market_data: Dict[str, List[MarketSnapshot]] = {}
        self.all_snapshots: List[MarketSnapshot] = []
    
    def load_data(self, filepath: str) -> int:
        """
        Load historical market data from JSON file.
        
        Expected format:
        [
            {
                "timestamp": "2024-01-15T00:00:00Z",
                "market_id": "0x123...",
                "question": "Will X happen?",
                "yes_price": 0.65,
                "no_price": 0.35,
                "volume": 150000,
                "volume_24h": 5000,
                "liquidity": 50000,
                "end_date": "2024-03-01T00:00:00Z",
                "resolved": false,
                "resolution": null
            },
            ...
        ]
        
        Returns:
            Number of snapshots loaded
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        for item in data:
            snapshot = MarketSnapshot(
                timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                market_id=item["market_id"],
                question=item.get("question", ""),
                yes_price=float(item["yes_price"]),
                no_price=float(item["no_price"]),
                volume=float(item.get("volume", 0)),
                volume_24h=float(item.get("volume_24h", 0)),
                liquidity=float(item.get("liquidity", 0)),
                end_date=datetime.fromisoformat(item["end_date"].replace("Z", "+00:00")) if item.get("end_date") else None,
                resolved=item.get("resolved", False),
                resolution=item.get("resolution")
            )
            
            self.all_snapshots.append(snapshot)
            
            if snapshot.market_id not in self.market_data:
                self.market_data[snapshot.market_id] = []
            self.market_data[snapshot.market_id].append(snapshot)
        
        # Sort by timestamp
        self.all_snapshots.sort(key=lambda x: x.timestamp)
        for market_id in self.market_data:
            self.market_data[market_id].sort(key=lambda x: x.timestamp)
        
        return len(self.all_snapshots)
    
    def generate_synthetic_data(
        self,
        num_markets: int = 50,
        days: int = 90,
        snapshots_per_day: int = 4
    ) -> int:
        """
        Generate synthetic market data for testing.
        
        Creates realistic-looking prediction markets with:
        - Random walk prices
        - Volume patterns
        - Resolution outcomes
        
        Returns:
            Number of snapshots generated
        """
        import random
        
        start_date = datetime.now() - timedelta(days=days)
        
        for i in range(num_markets):
            market_id = f"synthetic_{i:04d}"
            
            # Random market parameters
            initial_price = random.uniform(0.2, 0.8)
            volatility = random.uniform(0.01, 0.05)
            base_volume = random.uniform(10000, 500000)
            duration_days = random.randint(7, min(60, days))
            
            end_date = start_date + timedelta(days=random.randint(duration_days, days))
            
            # Determine resolution (biased toward initial probability)
            resolution = "YES" if random.random() < initial_price else "NO"
            
            price = initial_price
            
            for day in range(duration_days):
                current_date = start_date + timedelta(days=day)
                
                for snap in range(snapshots_per_day):
                    timestamp = current_date + timedelta(hours=snap * 6)
                    
                    # Random walk with mean reversion
                    drift = (initial_price - price) * 0.1  # Mean reversion
                    shock = random.gauss(0, volatility)
                    price = max(0.01, min(0.99, price + drift + shock))
                    
                    # Near resolution, move toward outcome
                    days_to_end = (end_date - timestamp).days
                    if days_to_end < 3:
                        target = 0.99 if resolution == "YES" else 0.01
                        price = price + (target - price) * 0.3
                    
                    resolved = timestamp >= end_date
                    
                    snapshot = MarketSnapshot(
                        timestamp=timestamp,
                        market_id=market_id,
                        question=f"Synthetic Market {i}: Will event occur?",
                        yes_price=round(price, 4),
                        no_price=round(1 - price, 4),
                        volume=base_volume * random.uniform(0.5, 1.5),
                        volume_24h=base_volume / 30 * random.uniform(0.5, 2.0),
                        liquidity=base_volume * 0.1 * random.uniform(0.8, 1.2),
                        end_date=end_date,
                        resolved=resolved,
                        resolution=resolution if resolved else None
                    )
                    
                    self.all_snapshots.append(snapshot)
                    
                    if market_id not in self.market_data:
                        self.market_data[market_id] = []
                    self.market_data[market_id].append(snapshot)
        
        # Sort
        self.all_snapshots.sort(key=lambda x: x.timestamp)
        for market_id in self.market_data:
            self.market_data[market_id].sort(key=lambda x: x.timestamp)
        
        return len(self.all_snapshots)
    
    def run(
        self,
        strategy: BaseStrategy,
        config: BacktestConfig
    ) -> BacktestResult:
        """
        Run backtest for a strategy.
        
        Args:
            strategy: Strategy instance to test
            config: Backtest configuration
            
        Returns:
            BacktestResult with performance metrics
        """
        # Reset strategy state
        strategy.state = StrategyState(capital=config.initial_capital)
        
        # Filter snapshots to date range
        snapshots = [
            s for s in self.all_snapshots
            if config.start_date <= s.timestamp <= config.end_date
        ]
        
        if not snapshots:
            raise ValueError("No data in specified date range")
        
        # Track equity curve
        equity_curve = []
        peak_equity = config.initial_capital
        max_drawdown = 0
        max_drawdown_pct = 0
        
        # Track exposure
        exposure_periods = 0
        total_periods = 0
        
        # Group snapshots by timestamp for daily processing
        from itertools import groupby
        
        snapshots_by_date = {}
        for snap in snapshots:
            date_key = snap.timestamp.date()
            if date_key not in snapshots_by_date:
                snapshots_by_date[date_key] = []
            snapshots_by_date[date_key].append(snap)
        
        # Process each day
        for date_key in sorted(snapshots_by_date.keys()):
            day_snapshots = snapshots_by_date[date_key]
            total_periods += 1
            
            # Check exits first
            for position in list(strategy.state.positions):
                # Find latest snapshot for this market
                market_snaps = [s for s in day_snapshots if s.market_id == position.market_id]
                if not market_snaps:
                    continue
                
                latest = market_snaps[-1]
                market_data = self._snapshot_to_dict(latest)
                
                # Check if market resolved
                if latest.resolved:
                    exit_price = 1.0 if latest.resolution == position.side else 0.0
                    exit_price *= (1 - config.commission)  # Apply commission
                    strategy.close_position(position, exit_price, latest.timestamp)
                    continue
                
                # Check strategy exit conditions
                if strategy.should_exit(position, market_data):
                    exit_price = latest.yes_price if position.side == "YES" else latest.no_price
                    exit_price *= (1 - config.commission - config.slippage)
                    strategy.close_position(position, exit_price, latest.timestamp)
            
            # Check entries
            if strategy.can_open_position():
                for snap in day_snapshots:
                    if not strategy.can_open_position():
                        break
                    
                    market_data = self._snapshot_to_dict(snap)
                    signal = strategy.generate_signal(market_data)
                    
                    if signal == Signal.BUY:
                        # Buy YES
                        size = strategy.calculate_position_size(market_data, signal)
                        price = snap.yes_price * (1 + config.commission + config.slippage)
                        
                        if price * size <= strategy.state.capital:
                            strategy.open_position(
                                market_id=snap.market_id,
                                outcome=snap.question,
                                side="YES",
                                price=price,
                                size=size / price,  # Convert to contracts
                                timestamp=snap.timestamp
                            )
                    
                    elif signal == Signal.SELL:
                        # Buy NO (sell YES)
                        size = strategy.calculate_position_size(market_data, signal)
                        price = snap.no_price * (1 + config.commission + config.slippage)
                        
                        if price * size <= strategy.state.capital:
                            strategy.open_position(
                                market_id=snap.market_id,
                                outcome=snap.question,
                                side="NO",
                                price=price,
                                size=size / price,
                                timestamp=snap.timestamp
                            )
            
            # Track exposure
            if strategy.state.positions:
                exposure_periods += 1
            
            # Calculate current equity
            current_equity = strategy.state.capital
            for pos in strategy.state.positions:
                # Mark to market
                market_snaps = [s for s in day_snapshots if s.market_id == pos.market_id]
                if market_snaps:
                    latest = market_snaps[-1]
                    current_price = latest.yes_price if pos.side == "YES" else latest.no_price
                    current_equity += current_price * pos.size
            
            # Track drawdown
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
                "positions": len(strategy.state.positions)
            })
        
        # Calculate final metrics
        trades = strategy.state.closed_trades
        winning_trades = [t for t in trades if t.won]
        losing_trades = [t for t in trades if not t.won]
        
        total_return = strategy.state.capital - config.initial_capital
        total_return_pct = total_return / config.initial_capital
        
        # Sharpe ratio (simplified)
        if trades:
            returns = [t.pnl_percent for t in trades]
            avg_return = sum(returns) / len(returns)
            std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe_ratio = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Profit factor
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        return BacktestResult(
            strategy_name=strategy.name,
            config=config,
            final_capital=strategy.state.capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=len(winning_trades) / len(trades) if trades else 0,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            profit_factor=profit_factor,
            avg_trade_pnl=sum(t.pnl for t in trades) / len(trades) if trades else 0,
            avg_win=sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0,
            avg_loss=sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0,
            best_trade=max(t.pnl for t in trades) if trades else 0,
            worst_trade=min(t.pnl for t in trades) if trades else 0,
            exposure_time_pct=exposure_periods / total_periods if total_periods > 0 else 0,
            equity_curve=equity_curve,
            trades=[{
                "market_id": t.market_id,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_percent,
                "won": t.won
            } for t in trades]
        )
    
    def _snapshot_to_dict(self, snap: MarketSnapshot) -> Dict[str, Any]:
        """Convert snapshot to dict for strategy consumption."""
        return {
            "market_id": snap.market_id,
            "question": snap.question,
            "yes_price": snap.yes_price,
            "no_price": snap.no_price,
            "volume": snap.volume,
            "volume_24h": snap.volume_24h,
            "liquidity": snap.liquidity,
            "end_date": snap.end_date,
            "resolved": snap.resolved,
            "resolution": snap.resolution,
            "closed": snap.resolved
        }


# CLI interface
if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    from src.strategies.longshot_bias import LongshotBiasStrategy
    
    parser = argparse.ArgumentParser(description="Run backtests")
    parser.add_argument("--strategy", default="longshot_bias", help="Strategy to test")
    parser.add_argument("--data", help="Path to historical data JSON")
    parser.add_argument("--synthetic", action="store_true", help="Generate synthetic data")
    parser.add_argument("--days", type=int, default=90, help="Days of synthetic data")
    parser.add_argument("--capital", type=float, default=10000, help="Initial capital")
    
    args = parser.parse_args()
    
    engine = BacktestEngine()
    
    if args.synthetic:
        print(f"Generating {args.days} days of synthetic data...")
        count = engine.generate_synthetic_data(days=args.days)
        print(f"Generated {count} market snapshots")
    elif args.data:
        count = engine.load_data(args.data)
        print(f"Loaded {count} market snapshots")
    else:
        print("Generating default synthetic data...")
        count = engine.generate_synthetic_data()
        print(f"Generated {count} market snapshots")
    
    # Select strategy
    if args.strategy == "longshot_bias":
        strategy = LongshotBiasStrategy()
    else:
        print(f"Unknown strategy: {args.strategy}")
        sys.exit(1)
    
    # Configure backtest
    config = BacktestConfig(
        start_date=datetime.now() - timedelta(days=args.days),
        end_date=datetime.now(),
        initial_capital=args.capital
    )
    
    print(f"\nRunning backtest for {strategy.name}...")
    result = engine.run(strategy, config)
    
    print(result.summary())
