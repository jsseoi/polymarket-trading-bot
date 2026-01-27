#!/usr/bin/env python3
"""
Paper Trading Simulator

Simulates live trading without real money.
Tracks virtual portfolio, P&L, and performance.

Usage:
    python -m src.paper_trading start        # Start paper trading session
    python -m src.paper_trading status       # Check portfolio status
    python -m src.paper_trading buy <market> # Buy YES on a market
    python -m src.paper_trading sell <market> # Buy NO on a market
    python -m src.paper_trading close <id>   # Close a position
"""

import json
import time
import os
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
import argparse

from .api.gamma_client import GammaClient


@dataclass
class Position:
    """A paper trading position."""
    id: str
    market_id: str
    question: str
    side: str  # "YES" or "NO"
    entry_price: float
    size: float
    entry_time: str
    current_price: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class Trade:
    """A completed trade."""
    id: str
    market_id: str
    question: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    entry_time: str
    exit_time: str
    pnl: float
    pnl_pct: float


@dataclass
class Portfolio:
    """Paper trading portfolio state."""
    cash: float = 10000.0
    initial_cash: float = 10000.0
    positions: List[Position] = field(default_factory=list)
    closed_trades: List[Trade] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()


class PaperTrader:
    """
    Paper trading simulator for Polymarket.
    
    Maintains a virtual portfolio and tracks performance
    against real market prices.
    """
    
    STATE_FILE = Path("data/paper_trading_state.json")
    
    def __init__(self):
        self.client = GammaClient()
        self.portfolio = self._load_state()
    
    def _load_state(self) -> Portfolio:
        """Load portfolio state from disk."""
        if self.STATE_FILE.exists():
            with open(self.STATE_FILE, 'r') as f:
                data = json.load(f)
                positions = [Position(**p) for p in data.get('positions', [])]
                trades = [Trade(**t) for t in data.get('closed_trades', [])]
                return Portfolio(
                    cash=data.get('cash', 10000),
                    initial_cash=data.get('initial_cash', 10000),
                    positions=positions,
                    closed_trades=trades,
                    created_at=data.get('created_at', ''),
                    updated_at=data.get('updated_at', '')
                )
        return Portfolio()
    
    def _save_state(self):
        """Save portfolio state to disk."""
        self.portfolio.updated_at = datetime.now().isoformat()
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'cash': self.portfolio.cash,
            'initial_cash': self.portfolio.initial_cash,
            'positions': [asdict(p) for p in self.portfolio.positions],
            'closed_trades': [asdict(t) for t in self.portfolio.closed_trades],
            'created_at': self.portfolio.created_at,
            'updated_at': self.portfolio.updated_at
        }
        
        with open(self.STATE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _generate_id(self) -> str:
        """Generate unique position/trade ID."""
        return f"{int(time.time() * 1000)}"
    
    def _get_market_price(self, market_id: str) -> Optional[tuple]:
        """Get current YES/NO prices for a market."""
        try:
            market = self.client.get_market(market_id)
            if market and market.outcome_prices:
                yes = market.outcome_prices[0]
                no = market.outcome_prices[1] if len(market.outcome_prices) > 1 else 1 - yes
                return (yes, no, market.question)
        except Exception:
            pass
        return None
    
    def _find_market(self, query: str) -> Optional[Dict]:
        """Search for a market by query."""
        try:
            markets = self.client.search_markets(query, limit=1)
            if markets:
                m = markets[0]
                return {
                    'id': m.condition_id,
                    'question': m.question,
                    'yes_price': m.outcome_prices[0] if m.outcome_prices else 0.5,
                    'no_price': m.outcome_prices[1] if len(m.outcome_prices) > 1 else 0.5
                }
        except Exception:
            pass
        return None
    
    def buy(self, query: str, amount: float, side: str = "YES") -> Optional[Position]:
        """
        Open a new position.
        
        Args:
            query: Market search query or ID
            amount: Dollar amount to invest
            side: "YES" or "NO"
            
        Returns:
            Position if successful, None otherwise
        """
        # Find market
        market = self._find_market(query)
        if not market:
            print(f"Market not found: {query}")
            return None
        
        # Check cash
        if amount > self.portfolio.cash:
            print(f"Insufficient funds. Available: ${self.portfolio.cash:.2f}")
            return None
        
        # Calculate position
        price = market['yes_price'] if side == "YES" else market['no_price']
        size = amount / price  # Number of contracts
        
        position = Position(
            id=self._generate_id(),
            market_id=market['id'],
            question=market['question'],
            side=side,
            entry_price=price,
            size=size,
            entry_time=datetime.now().isoformat(),
            current_price=price
        )
        
        # Update portfolio
        self.portfolio.cash -= amount
        self.portfolio.positions.append(position)
        self._save_state()
        
        print(f"\n✅ Position opened:")
        print(f"   {side} on: {market['question'][:50]}...")
        print(f"   Entry: {price:.2%} | Size: {size:.2f} contracts | Cost: ${amount:.2f}")
        
        return position
    
    def close(self, position_id: str) -> Optional[Trade]:
        """
        Close a position.
        
        Args:
            position_id: ID of position to close
            
        Returns:
            Trade record if successful
        """
        # Find position
        position = None
        for p in self.portfolio.positions:
            if p.id == position_id:
                position = p
                break
        
        if not position:
            print(f"Position not found: {position_id}")
            return None
        
        # Get current price
        prices = self._get_market_price(position.market_id)
        if not prices:
            print(f"Could not get current price for market")
            return None
        
        yes_price, no_price, _ = prices
        exit_price = yes_price if position.side == "YES" else no_price
        
        # Calculate P&L
        exit_value = exit_price * position.size
        entry_value = position.entry_price * position.size
        pnl = exit_value - entry_value
        pnl_pct = pnl / entry_value if entry_value > 0 else 0
        
        # Create trade record
        trade = Trade(
            id=position.id,
            market_id=position.market_id,
            question=position.question,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            size=position.size,
            entry_time=position.entry_time,
            exit_time=datetime.now().isoformat(),
            pnl=pnl,
            pnl_pct=pnl_pct
        )
        
        # Update portfolio
        self.portfolio.cash += exit_value
        self.portfolio.positions.remove(position)
        self.portfolio.closed_trades.append(trade)
        self._save_state()
        
        emoji = "🟢" if pnl > 0 else "🔴"
        print(f"\n{emoji} Position closed:")
        print(f"   {position.side} on: {position.question[:50]}...")
        print(f"   Entry: {position.entry_price:.2%} → Exit: {exit_price:.2%}")
        print(f"   P&L: ${pnl:+.2f} ({pnl_pct:+.1%})")
        
        return trade
    
    def update_prices(self):
        """Update current prices for all positions."""
        for position in self.portfolio.positions:
            prices = self._get_market_price(position.market_id)
            if prices:
                yes_price, no_price, _ = prices
                position.current_price = yes_price if position.side == "YES" else no_price
                
                entry_value = position.entry_price * position.size
                current_value = position.current_price * position.size
                position.pnl = current_value - entry_value
                position.pnl_pct = position.pnl / entry_value if entry_value > 0 else 0
        
        self._save_state()
    
    def status(self):
        """Print portfolio status."""
        self.update_prices()
        
        # Calculate totals
        position_value = sum(p.current_price * p.size for p in self.portfolio.positions)
        total_value = self.portfolio.cash + position_value
        total_pnl = total_value - self.portfolio.initial_cash
        total_pnl_pct = total_pnl / self.portfolio.initial_cash
        
        # Win rate
        wins = sum(1 for t in self.portfolio.closed_trades if t.pnl > 0)
        total_trades = len(self.portfolio.closed_trades)
        win_rate = wins / total_trades if total_trades > 0 else 0
        
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║  PAPER TRADING PORTFOLIO                                             ║
╠══════════════════════════════════════════════════════════════════════╣
║  Cash:              ${self.portfolio.cash:>12,.2f}
║  Positions Value:   ${position_value:>12,.2f}
║  ─────────────────────────────────────────────────────────────────
║  Total Value:       ${total_value:>12,.2f}
║  Total P&L:         ${total_pnl:>+12,.2f} ({total_pnl_pct:+.1%})
║  ─────────────────────────────────────────────────────────────────
║  Trades Closed:     {total_trades:>12}
║  Win Rate:          {win_rate:>12.1%}
╠══════════════════════════════════════════════════════════════════════╣""")
        
        if self.portfolio.positions:
            print("║  OPEN POSITIONS")
            print("║  ─────────────────────────────────────────────────────────────────")
            for p in self.portfolio.positions:
                emoji = "🟢" if p.pnl > 0 else "🔴" if p.pnl < 0 else "⚪"
                print(f"║  {emoji} [{p.id}] {p.side} {p.question[:40]}...")
                print(f"║     Entry: {p.entry_price:.2%} → Now: {p.current_price:.2%} | P&L: ${p.pnl:+.2f}")
        else:
            print("║  No open positions")
        
        print("╚══════════════════════════════════════════════════════════════════════╝\n")
    
    def reset(self, initial_cash: float = 10000):
        """Reset portfolio to initial state."""
        self.portfolio = Portfolio(cash=initial_cash, initial_cash=initial_cash)
        self._save_state()
        print(f"Portfolio reset with ${initial_cash:,.2f}")


def main():
    parser = argparse.ArgumentParser(description="Paper Trading Simulator")
    subparsers = parser.add_subparsers(dest="command")
    
    # status
    subparsers.add_parser("status", help="Show portfolio status")
    
    # buy
    p_buy = subparsers.add_parser("buy", help="Buy YES on a market")
    p_buy.add_argument("market", help="Market query")
    p_buy.add_argument("-a", "--amount", type=float, default=100, help="Amount to invest")
    
    # sell (buy NO)
    p_sell = subparsers.add_parser("sell", help="Buy NO on a market")
    p_sell.add_argument("market", help="Market query")
    p_sell.add_argument("-a", "--amount", type=float, default=100, help="Amount to invest")
    
    # close
    p_close = subparsers.add_parser("close", help="Close a position")
    p_close.add_argument("position_id", help="Position ID to close")
    
    # reset
    p_reset = subparsers.add_parser("reset", help="Reset portfolio")
    p_reset.add_argument("-c", "--cash", type=float, default=10000, help="Initial cash")
    
    args = parser.parse_args()
    
    trader = PaperTrader()
    
    if args.command == "status" or not args.command:
        trader.status()
    elif args.command == "buy":
        trader.buy(args.market, args.amount, "YES")
    elif args.command == "sell":
        trader.buy(args.market, args.amount, "NO")
    elif args.command == "close":
        trader.close(args.position_id)
    elif args.command == "reset":
        trader.reset(args.cash)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
