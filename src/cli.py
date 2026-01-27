#!/usr/bin/env python3
"""
Polymarket Trading Bot CLI

Command-line interface for running strategies and analysis.

Usage:
    python -m src.cli markets           # List active markets
    python -m src.cli scan              # Scan for opportunities
    python -m src.cli backtest          # Run backtests
    python -m src.cli analyze <market>  # Analyze specific market
"""

import argparse
import sys
from datetime import datetime, timedelta
from typing import Optional

from .api.gamma_client import GammaClient
from .strategies.longshot_bias import LongshotBiasStrategy
from .strategies.arbitrage import ArbitrageStrategy
from .strategies.momentum import MomentumStrategy
from .strategies.mean_reversion import MeanReversionStrategy
from .backtesting.engine import BacktestEngine, BacktestConfig


def cmd_markets(args):
    """List active markets."""
    client = GammaClient()
    
    print(f"\n{'='*70}")
    print(f"  POLYMARKET - Active Markets (Top {args.limit} by volume)")
    print(f"{'='*70}\n")
    
    try:
        markets = client.get_markets(
            active=True,
            closed=False,
            limit=args.limit,
            order="volume"
        )
        
        for i, m in enumerate(markets, 1):
            prob = m.outcome_prices[0] if m.outcome_prices else 0.5
            print(f"{i:2}. [{prob*100:5.1f}%] {m.question[:60]}")
            print(f"    Volume: ${m.volume:,.0f} | Liquidity: ${m.liquidity:,.0f}")
            print()
            
    except Exception as e:
        print(f"Error fetching markets: {e}")
        return 1
    
    return 0


def cmd_scan(args):
    """Scan markets for trading opportunities."""
    client = GammaClient()
    
    print(f"\n{'='*70}")
    print(f"  OPPORTUNITY SCANNER")
    print(f"{'='*70}\n")
    
    # Initialize strategies
    strategies = [
        ("Longshot Bias", LongshotBiasStrategy()),
        ("Arbitrage", ArbitrageStrategy()),
        ("Mean Reversion", MeanReversionStrategy()),
    ]
    
    try:
        markets = client.get_markets(active=True, limit=100, order="volume")
        
        opportunities = []
        
        for m in markets:
            market_data = {
                "market_id": m.condition_id,
                "question": m.question,
                "yes_price": m.outcome_prices[0] if m.outcome_prices else 0.5,
                "no_price": m.outcome_prices[1] if len(m.outcome_prices) > 1 else 0.5,
                "volume": m.volume,
                "liquidity": m.liquidity,
                "end_date": m.end_date
            }
            
            for strat_name, strategy in strategies:
                signal = strategy.generate_signal(market_data)
                
                if signal.value in ["BUY", "SELL"]:
                    opportunities.append({
                        "strategy": strat_name,
                        "signal": signal.value,
                        "market": m.question[:50],
                        "price": market_data["yes_price"],
                        "volume": m.volume
                    })
        
        if opportunities:
            print(f"Found {len(opportunities)} opportunities:\n")
            
            for opp in sorted(opportunities, key=lambda x: x["volume"], reverse=True)[:20]:
                print(f"  [{opp['strategy']}] {opp['signal']}")
                print(f"    {opp['market']}...")
                print(f"    Price: {opp['price']:.2%} | Volume: ${opp['volume']:,.0f}")
                print()
        else:
            print("No opportunities found with current criteria.")
            
    except Exception as e:
        print(f"Error scanning: {e}")
        return 1
    
    return 0


def cmd_backtest(args):
    """Run backtests on strategies."""
    print(f"\n{'='*70}")
    print(f"  BACKTEST - {args.strategy} Strategy")
    print(f"{'='*70}\n")
    
    # Initialize engine
    engine = BacktestEngine()
    
    # Generate or load data
    if args.data:
        print(f"Loading data from {args.data}...")
        engine.load_data(args.data)
    else:
        print(f"Generating {args.days} days of synthetic data...")
        engine.generate_synthetic_data(num_markets=50, days=args.days)
    
    # Select strategy
    strategy_map = {
        "longshot": LongshotBiasStrategy(),
        "arbitrage": ArbitrageStrategy(),
        "momentum": MomentumStrategy(),
        "mean_reversion": MeanReversionStrategy(),
    }
    
    strategy = strategy_map.get(args.strategy)
    if not strategy:
        print(f"Unknown strategy: {args.strategy}")
        print(f"Available: {', '.join(strategy_map.keys())}")
        return 1
    
    # Configure backtest
    config = BacktestConfig(
        start_date=datetime.now() - timedelta(days=args.days),
        end_date=datetime.now(),
        initial_capital=args.capital,
        commission=0.02,
        slippage=0.005
    )
    
    # Run
    print(f"Running backtest...")
    result = engine.run(strategy, config)
    
    # Display results
    print(result.summary())
    
    return 0


def cmd_analyze(args):
    """Analyze a specific market."""
    client = GammaClient()
    
    print(f"\n{'='*70}")
    print(f"  MARKET ANALYSIS")
    print(f"{'='*70}\n")
    
    try:
        # Search for market
        markets = client.search_markets(args.query, limit=5)
        
        if not markets:
            print(f"No markets found for: {args.query}")
            return 1
        
        m = markets[0]  # Take first result
        
        print(f"Market: {m.question}\n")
        print(f"{'─'*50}")
        print(f"  Condition ID: {m.condition_id}")
        print(f"  End Date:     {m.end_date}")
        print(f"  Active:       {m.active}")
        print(f"  Closed:       {m.closed}")
        print(f"{'─'*50}")
        print(f"  YES Price:    {m.outcome_prices[0]:.2%}" if m.outcome_prices else "  Prices: N/A")
        print(f"  NO Price:     {m.outcome_prices[1]:.2%}" if len(m.outcome_prices) > 1 else "")
        print(f"  Spread:       {m.spread:.2%}")
        print(f"{'─'*50}")
        print(f"  Volume:       ${m.volume:,.0f}")
        print(f"  Liquidity:    ${m.liquidity:,.0f}")
        print(f"{'─'*50}\n")
        
        # Run strategy signals
        market_data = {
            "market_id": m.condition_id,
            "question": m.question,
            "yes_price": m.outcome_prices[0] if m.outcome_prices else 0.5,
            "no_price": m.outcome_prices[1] if len(m.outcome_prices) > 1 else 0.5,
            "volume": m.volume,
            "liquidity": m.liquidity,
            "end_date": m.end_date
        }
        
        print("Strategy Signals:")
        print(f"{'─'*50}")
        
        strategies = [
            ("Longshot Bias", LongshotBiasStrategy()),
            ("Arbitrage", ArbitrageStrategy()),
            ("Momentum", MomentumStrategy()),
            ("Mean Reversion", MeanReversionStrategy()),
        ]
        
        for name, strat in strategies:
            signal = strat.generate_signal(market_data)
            emoji = "🟢" if signal.value == "BUY" else "🔴" if signal.value == "SELL" else "⚪"
            print(f"  {emoji} {name:20} → {signal.value}")
        
        print()
        
    except Exception as e:
        print(f"Error analyzing market: {e}")
        return 1
    
    return 0


def cmd_compare(args):
    """Compare all strategies."""
    print(f"\n{'='*70}")
    print(f"  STRATEGY COMPARISON")
    print(f"{'='*70}\n")
    
    engine = BacktestEngine()
    print(f"Generating {args.days} days of synthetic data...")
    engine.generate_synthetic_data(num_markets=50, days=args.days)
    
    config = BacktestConfig(
        start_date=datetime.now() - timedelta(days=args.days),
        end_date=datetime.now(),
        initial_capital=args.capital
    )
    
    strategies = [
        ("Longshot", LongshotBiasStrategy()),
        ("Arbitrage", ArbitrageStrategy()),
        ("Momentum", MomentumStrategy()),
        ("MeanRev", MeanReversionStrategy()),
    ]
    
    results = []
    for name, strat in strategies:
        print(f"Testing {name}...")
        result = engine.run(strat, config)
        results.append((name, result))
    
    print(f"\n{'Strategy':<12} {'Return':>10} {'Win Rate':>10} {'Trades':>8} {'Sharpe':>8}")
    print("─" * 50)
    
    for name, r in sorted(results, key=lambda x: x[1].total_return_pct, reverse=True):
        print(f"{name:<12} {r.total_return_pct:>9.1%} {r.win_rate:>9.1%} {r.total_trades:>8} {r.sharpe_ratio:>7.2f}")
    
    print()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Trading Bot CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.cli markets                    # List top markets
  python -m src.cli scan                       # Scan for opportunities
  python -m src.cli backtest -s longshot       # Backtest longshot strategy
  python -m src.cli analyze "Trump"            # Analyze Trump-related markets
  python -m src.cli compare                    # Compare all strategies
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # markets command
    p_markets = subparsers.add_parser("markets", help="List active markets")
    p_markets.add_argument("-l", "--limit", type=int, default=20, help="Number of markets")
    
    # scan command
    p_scan = subparsers.add_parser("scan", help="Scan for opportunities")
    
    # backtest command
    p_backtest = subparsers.add_parser("backtest", help="Run backtests")
    p_backtest.add_argument("-s", "--strategy", default="longshot",
                           choices=["longshot", "arbitrage", "momentum", "mean_reversion"],
                           help="Strategy to test")
    p_backtest.add_argument("-d", "--days", type=int, default=90, help="Days of history")
    p_backtest.add_argument("-c", "--capital", type=float, default=10000, help="Initial capital")
    p_backtest.add_argument("--data", help="Path to historical data JSON")
    
    # analyze command
    p_analyze = subparsers.add_parser("analyze", help="Analyze a market")
    p_analyze.add_argument("query", help="Market search query")
    
    # compare command
    p_compare = subparsers.add_parser("compare", help="Compare all strategies")
    p_compare.add_argument("-d", "--days", type=int, default=90, help="Days of history")
    p_compare.add_argument("-c", "--capital", type=float, default=10000, help="Initial capital")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    commands = {
        "markets": cmd_markets,
        "scan": cmd_scan,
        "backtest": cmd_backtest,
        "analyze": cmd_analyze,
        "compare": cmd_compare,
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
