"""
Base Strategy Class

All trading strategies inherit from this base class.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


class Signal(Enum):
    """Trading signal types."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Position:
    """Represents an open position."""
    market_id: str
    outcome: str
    side: str  # "YES" or "NO"
    entry_price: float
    size: float
    entry_time: datetime
    
    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.size


@dataclass
class TradeResult:
    """Result of a completed trade."""
    market_id: str
    outcome: str
    entry_price: float
    exit_price: float
    size: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_percent: float
    won: bool


@dataclass 
class StrategyState:
    """Tracks strategy state during backtesting."""
    capital: float = 10000.0
    positions: List[Position] = field(default_factory=list)
    closed_trades: List[TradeResult] = field(default_factory=list)
    
    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades)
    
    @property
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        wins = sum(1 for t in self.closed_trades if t.won)
        return wins / len(self.closed_trades)
    
    @property
    def total_trades(self) -> int:
        return len(self.closed_trades)


class BaseStrategy(ABC):
    """
    Abstract base class for trading strategies.
    
    Subclasses must implement:
    - generate_signal(): Analyze market and return a Signal
    - should_exit(): Determine if position should be closed
    """
    
    def __init__(
        self,
        name: str,
        max_position_size: float = 0.1,  # Max % of capital per trade
        max_positions: int = 10,
        min_edge: float = 0.02  # Minimum expected edge to trade
    ):
        self.name = name
        self.max_position_size = max_position_size
        self.max_positions = max_positions
        self.min_edge = min_edge
        self.state = StrategyState()
    
    @abstractmethod
    def generate_signal(
        self,
        market_data: Dict[str, Any],
        historical_data: Optional[List[Dict]] = None
    ) -> Signal:
        """
        Analyze market and generate trading signal.
        
        Args:
            market_data: Current market state (prices, volume, etc.)
            historical_data: Optional historical price/volume data
            
        Returns:
            Signal indicating BUY, SELL, or HOLD
        """
        pass
    
    @abstractmethod
    def should_exit(
        self,
        position: Position,
        market_data: Dict[str, Any]
    ) -> bool:
        """
        Determine if an existing position should be closed.
        
        Args:
            position: Current open position
            market_data: Current market state
            
        Returns:
            True if position should be closed
        """
        pass
    
    def calculate_position_size(
        self,
        market_data: Dict[str, Any],
        signal: Signal
    ) -> float:
        """
        Calculate position size based on Kelly Criterion or fixed fraction.
        
        Override this method for custom position sizing.
        """
        available_capital = self.state.capital
        max_size = available_capital * self.max_position_size
        
        # Simple fixed fraction for now
        return max_size
    
    def can_open_position(self) -> bool:
        """Check if we can open a new position."""
        return len(self.state.positions) < self.max_positions
    
    def open_position(
        self,
        market_id: str,
        outcome: str,
        side: str,
        price: float,
        size: float,
        timestamp: datetime
    ) -> Position:
        """Open a new position."""
        position = Position(
            market_id=market_id,
            outcome=outcome,
            side=side,
            entry_price=price,
            size=size,
            entry_time=timestamp
        )
        self.state.positions.append(position)
        self.state.capital -= position.cost_basis
        
        return position
    
    def close_position(
        self,
        position: Position,
        exit_price: float,
        timestamp: datetime
    ) -> TradeResult:
        """Close an existing position."""
        # Calculate P&L
        if position.side == "YES":
            # Bought YES: profit if price goes up or settles YES (1.0)
            pnl = (exit_price - position.entry_price) * position.size
        else:
            # Bought NO: profit if price goes down or settles NO (1.0 for NO token)
            pnl = (exit_price - position.entry_price) * position.size
        
        pnl_percent = pnl / position.cost_basis if position.cost_basis > 0 else 0
        
        result = TradeResult(
            market_id=position.market_id,
            outcome=position.outcome,
            entry_price=position.entry_price,
            exit_price=exit_price,
            size=position.size,
            entry_time=position.entry_time,
            exit_time=timestamp,
            pnl=pnl,
            pnl_percent=pnl_percent,
            won=pnl > 0
        )
        
        # Update state
        self.state.positions.remove(position)
        self.state.closed_trades.append(result)
        self.state.capital += exit_price * position.size
        
        return result
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get strategy performance metrics."""
        trades = self.state.closed_trades
        
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0,
                "max_drawdown": 0,
                "sharpe_ratio": 0
            }
        
        pnls = [t.pnl for t in trades]
        winning_trades = [t for t in trades if t.won]
        losing_trades = [t for t in trades if not t.won]
        
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        return {
            "total_trades": len(trades),
            "win_rate": self.state.win_rate,
            "total_pnl": self.state.total_pnl,
            "avg_pnl": sum(pnls) / len(pnls),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": abs(avg_win / avg_loss) if avg_loss != 0 else float('inf'),
            "final_capital": self.state.capital
        }
