#!/usr/bin/env python3
"""
Strategy Analysis Script

Runs backtests on all strategies and generates a comparison report.
Can be run as a script or converted to Jupyter notebook.

Usage:
    python strategy_analysis.py
    
    # Or in Jupyter:
    # jupyter notebook strategy_analysis.ipynb
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.engine import BacktestEngine, BacktestConfig, BacktestResult
from src.strategies.longshot_bias import LongshotBiasStrategy
from src.strategies.arbitrage import ArbitrageStrategy
from src.strategies.momentum import MomentumStrategy


def run_strategy_comparison(days: int = 90, initial_capital: float = 10000) -> Dict[str, BacktestResult]:
    """
    Run backtests on all strategies and compare results.
    
    Args:
        days: Number of days to backtest
        initial_capital: Starting capital
        
    Returns:
        Dict mapping strategy name to BacktestResult
    """
    print("=" * 60)
    print("POLYMARKET STRATEGY COMPARISON")
    print("=" * 60)
    print(f"\nBacktest Period: {days} days")
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Data: Synthetic (for demonstration)")
    print()
    
    # Initialize backtesting engine with synthetic data
    engine = BacktestEngine()
    print("Generating synthetic market data...")
    num_snapshots = engine.generate_synthetic_data(
        num_markets=50,
        days=days,
        snapshots_per_day=4
    )
    print(f"Generated {num_snapshots:,} market snapshots\n")
    
    # Configure backtest
    config = BacktestConfig(
        start_date=datetime.now() - timedelta(days=days),
        end_date=datetime.now(),
        initial_capital=initial_capital,
        commission=0.02,
        slippage=0.005,
        max_position_pct=0.1
    )
    
    # Initialize strategies
    strategies = [
        LongshotBiasStrategy(
            favorite_threshold=0.70,
            longshot_threshold=0.20,
            volume_min=10000
        ),
        ArbitrageStrategy(
            min_spread=0.02,
            min_profit_pct=0.01,
            fee_rate=0.02
        ),
        MomentumStrategy(
            lookback_minutes=60,
            min_price_change=0.05,
            min_volume_increase=2.0
        ),
    ]
    
    # Run backtests
    results = {}
    for strategy in strategies:
        print(f"Running backtest: {strategy.name}...")
        try:
            result = engine.run(strategy, config)
            results[strategy.name] = result
            print(f"  Completed: {result.total_trades} trades, {result.win_rate:.1%} win rate")
        except Exception as e:
            print(f"  Error: {e}")
    
    return results


def print_comparison_table(results: Dict[str, BacktestResult]) -> None:
    """Print a comparison table of all strategies."""
    
    print("\n" + "=" * 80)
    print("STRATEGY COMPARISON TABLE")
    print("=" * 80)
    
    # Header
    print(f"\n{'Strategy':<15} {'Return':>10} {'Win Rate':>10} {'Trades':>8} {'Max DD':>10} {'Sharpe':>8} {'PF':>8}")
    print("-" * 80)
    
    # Sort by total return
    sorted_results = sorted(
        results.items(),
        key=lambda x: x[1].total_return_pct,
        reverse=True
    )
    
    for name, r in sorted_results:
        print(f"{name:<15} {r.total_return_pct:>9.1%} {r.win_rate:>9.1%} {r.total_trades:>8} "
              f"{r.max_drawdown_pct:>9.1%} {r.sharpe_ratio:>7.2f} {r.profit_factor:>7.2f}")
    
    print("-" * 80)


def print_detailed_results(results: Dict[str, BacktestResult]) -> None:
    """Print detailed results for each strategy."""
    
    for name, result in results.items():
        print(result.summary())


def analyze_trade_distribution(results: Dict[str, BacktestResult]) -> None:
    """Analyze trade P&L distribution for each strategy."""
    
    print("\n" + "=" * 60)
    print("TRADE DISTRIBUTION ANALYSIS")
    print("=" * 60)
    
    for name, result in results.items():
        if not result.trades:
            continue
            
        pnls = [t["pnl"] for t in result.trades]
        pnl_pcts = [t["pnl_pct"] for t in result.trades]
        
        print(f"\n{name}")
        print("-" * 40)
        
        # Quintile analysis
        sorted_pnls = sorted(pnl_pcts)
        n = len(sorted_pnls)
        
        if n >= 5:
            q1 = sorted_pnls[n // 5]
            q2 = sorted_pnls[2 * n // 5]
            q3 = sorted_pnls[3 * n // 5]
            q4 = sorted_pnls[4 * n // 5]
            
            print(f"  Bottom 20%: {q1:>7.1%}")
            print(f"  20-40%:     {q2:>7.1%}")
            print(f"  40-60%:     {q3:>7.1%}")
            print(f"  60-80%:     {q4:>7.1%}")
            print(f"  Top 20%:    {sorted_pnls[-1]:>7.1%}")
        
        # Win/loss breakdown
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        if wins:
            print(f"\n  Wins ({len(wins)}):")
            print(f"    Avg: ${sum(wins)/len(wins):,.2f}")
            print(f"    Max: ${max(wins):,.2f}")
        
        if losses:
            print(f"\n  Losses ({len(losses)}):")
            print(f"    Avg: ${sum(losses)/len(losses):,.2f}")
            print(f"    Max: ${min(losses):,.2f}")


def generate_equity_curves(results: Dict[str, BacktestResult]) -> str:
    """Generate ASCII equity curves for visualization."""
    
    output = []
    output.append("\n" + "=" * 60)
    output.append("EQUITY CURVES (ASCII)")
    output.append("=" * 60)
    
    for name, result in results.items():
        if not result.equity_curve:
            continue
        
        equities = [point["equity"] for point in result.equity_curve]
        
        if len(equities) < 2:
            continue
        
        # Normalize to 50 columns
        width = 50
        min_eq = min(equities)
        max_eq = max(equities)
        range_eq = max_eq - min_eq if max_eq > min_eq else 1
        
        output.append(f"\n{name}")
        output.append(f"Start: ${equities[0]:,.0f} → End: ${equities[-1]:,.0f}")
        output.append("-" * (width + 10))
        
        # Sample points for display
        step = max(1, len(equities) // 20)
        sampled = equities[::step][:20]
        
        for i, eq in enumerate(sampled):
            bar_len = int((eq - min_eq) / range_eq * width)
            bar = "█" * bar_len
            output.append(f"  {bar} ${eq:,.0f}")
        
        output.append("-" * (width + 10))
    
    return "\n".join(output)


def main():
    """Main entry point."""
    
    print("\n" + "🎰" * 20)
    print("  POLYMARKET TRADING BOT - STRATEGY ANALYSIS")
    print("🎰" * 20 + "\n")
    
    # Run comparison
    results = run_strategy_comparison(days=90, initial_capital=10000)
    
    if not results:
        print("No results to display. Check for errors above.")
        return
    
    # Print comparison
    print_comparison_table(results)
    
    # Print detailed results
    print_detailed_results(results)
    
    # Analyze trades
    analyze_trade_distribution(results)
    
    # Generate equity curves
    print(generate_equity_curves(results))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY & RECOMMENDATIONS")
    print("=" * 60)
    
    best_return = max(results.items(), key=lambda x: x[1].total_return_pct)
    best_sharpe = max(results.items(), key=lambda x: x[1].sharpe_ratio)
    best_winrate = max(results.items(), key=lambda x: x[1].win_rate)
    
    print(f"""
Best Total Return:  {best_return[0]} ({best_return[1].total_return_pct:.1%})
Best Sharpe Ratio:  {best_sharpe[0]} ({best_sharpe[1].sharpe_ratio:.2f})
Best Win Rate:      {best_winrate[0]} ({best_winrate[1].win_rate:.1%})

Recommendations:
1. For consistent returns: Consider {best_sharpe[0]} (best risk-adjusted returns)
2. For high win rate: Consider {best_winrate[0]} (highest probability of winning trades)
3. For maximum growth: Consider {best_return[0]} (highest total returns)

Note: These are backtested results on synthetic data. Real-world performance
may differ significantly due to:
- Market microstructure (slippage, order execution)
- Competition from other traders
- Regime changes in market behavior
- Black swan events

Always start with small positions and validate strategies on live markets
before scaling up.
""")
    
    print("=" * 60)
    print("Analysis complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
