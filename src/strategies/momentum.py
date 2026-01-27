"""
Momentum Strategy

Trades based on price momentum and news velocity.

Core insight: Prediction markets often underreact to new information,
creating momentum effects that can be exploited.

Research shows:
- Markets take 15-60 minutes to fully incorporate breaking news
- Strong directional moves often continue (momentum)
- Volume spikes precede major price moves

This strategy:
1. Detects rapid price changes
2. Confirms with volume increase
3. Enters in direction of momentum
4. Exits on momentum exhaustion or reversal
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque
from .base_strategy import BaseStrategy, Signal, Position


@dataclass
class PricePoint:
    """A historical price observation."""
    timestamp: datetime
    price: float
    volume: float


class MomentumStrategy(BaseStrategy):
    """
    News velocity and price momentum strategy.
    
    Identifies markets with strong directional moves and trades
    in the direction of momentum.
    
    Parameters:
        lookback_minutes: Window for calculating momentum
        min_price_change: Minimum price change to trigger signal
        min_volume_increase: Minimum volume increase multiplier
        momentum_decay_hours: How long momentum typically lasts
        reversal_threshold: Price reversal that triggers exit
    """
    
    def __init__(
        self,
        lookback_minutes: int = 60,
        min_price_change: float = 0.05,  # 5% price move
        min_volume_increase: float = 2.0,  # 2x normal volume
        momentum_decay_hours: int = 4,
        reversal_threshold: float = 0.03,  # 3% reversal triggers exit
        **kwargs
    ):
        super().__init__(name="Momentum", **kwargs)
        self.lookback_minutes = lookback_minutes
        self.min_price_change = min_price_change
        self.min_volume_increase = min_volume_increase
        self.momentum_decay_hours = momentum_decay_hours
        self.reversal_threshold = reversal_threshold
        
        # Price history per market
        self.price_history: Dict[str, deque] = {}
        self.max_history = 100  # Max observations per market
    
    def update_price_history(
        self,
        market_id: str,
        price: float,
        volume: float,
        timestamp: Optional[datetime] = None
    ) -> None:
        """
        Update price history for a market.
        
        Call this before generate_signal for accurate momentum calculation.
        """
        if market_id not in self.price_history:
            self.price_history[market_id] = deque(maxlen=self.max_history)
        
        ts = timestamp or datetime.now()
        self.price_history[market_id].append(PricePoint(
            timestamp=ts,
            price=price,
            volume=volume
        ))
    
    def generate_signal(
        self,
        market_data: Dict[str, Any],
        historical_data: Optional[List[Dict]] = None
    ) -> Signal:
        """
        Generate signal based on price momentum.
        
        Looks for:
        1. Significant price change in lookback window
        2. Volume confirmation (higher than normal)
        3. No signs of reversal yet
        """
        market_id = market_data.get("market_id", "")
        yes_price = market_data.get("yes_price", 0.5)
        volume_24h = market_data.get("volume_24h", 0)
        liquidity = market_data.get("liquidity", 0)
        end_date = market_data.get("end_date")
        
        # Don't trade illiquid markets
        if liquidity < 5000:
            return Signal.HOLD
        
        # Don't trade markets about to expire
        if end_date:
            hours_to_expiry = (end_date - datetime.now()).total_seconds() / 3600
            if hours_to_expiry < 12:
                return Signal.HOLD
        
        # Update history if we have historical data
        if historical_data:
            for point in historical_data[-self.max_history:]:
                self.update_price_history(
                    market_id,
                    point.get("yes_price", 0.5),
                    point.get("volume_24h", 0),
                    datetime.fromisoformat(point["timestamp"]) if "timestamp" in point else None
                )
        
        # Calculate momentum
        momentum = self._calculate_momentum(market_id, yes_price, volume_24h)
        
        if momentum is None:
            return Signal.HOLD
        
        price_change, volume_ratio, direction = momentum
        
        # Check if momentum is strong enough
        if abs(price_change) < self.min_price_change:
            return Signal.HOLD
        
        if volume_ratio < self.min_volume_increase:
            return Signal.HOLD
        
        # Generate signal in direction of momentum
        if direction > 0:
            # Upward momentum - buy YES
            return Signal.BUY
        elif direction < 0:
            # Downward momentum - buy NO (sell YES)
            return Signal.SELL
        
        return Signal.HOLD
    
    def _calculate_momentum(
        self,
        market_id: str,
        current_price: float,
        current_volume: float
    ) -> Optional[tuple]:
        """
        Calculate momentum metrics.
        
        Returns:
            Tuple of (price_change, volume_ratio, direction) or None
        """
        history = self.price_history.get(market_id)
        
        if not history or len(history) < 3:
            return None
        
        # Get price from lookback window
        lookback_time = datetime.now() - timedelta(minutes=self.lookback_minutes)
        
        old_points = [p for p in history if p.timestamp <= lookback_time]
        if not old_points:
            old_points = [history[0]]
        
        old_price = old_points[-1].price
        
        # Calculate price change
        price_change = (current_price - old_price) / old_price if old_price > 0 else 0
        
        # Calculate average historical volume
        volumes = [p.volume for p in history]
        avg_volume = sum(volumes) / len(volumes) if volumes else current_volume
        
        # Volume ratio
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # Direction
        if price_change > 0.01:
            direction = 1
        elif price_change < -0.01:
            direction = -1
        else:
            direction = 0
        
        return (price_change, volume_ratio, direction)
    
    def should_exit(
        self,
        position: Position,
        market_data: Dict[str, Any]
    ) -> bool:
        """
        Exit conditions for momentum trades.
        
        1. Market resolved
        2. Momentum exhausted (time decay)
        3. Price reversal detected
        4. Target profit reached
        """
        is_closed = market_data.get("closed", False)
        current_price = market_data.get("yes_price", 0.5)
        
        # Exit if resolved
        if is_closed:
            return True
        
        # Exit if momentum window expired
        hours_held = (datetime.now() - position.entry_time).total_seconds() / 3600
        if hours_held > self.momentum_decay_hours:
            return True
        
        # Check for reversal
        if position.side == "YES":
            # Bought YES, exit if price drops significantly
            pnl_pct = (current_price - position.entry_price) / position.entry_price
            
            # Exit on reversal
            if pnl_pct < -self.reversal_threshold:
                return True
            
            # Take profit at 10%+
            if pnl_pct > 0.10:
                return True
        
        else:  # position.side == "NO"
            no_price = 1.0 - current_price
            pnl_pct = (no_price - position.entry_price) / position.entry_price
            
            if pnl_pct < -self.reversal_threshold:
                return True
            
            if pnl_pct > 0.10:
                return True
        
        return False
    
    def detect_news_event(
        self,
        market_data: Dict[str, Any],
        price_history: List[float]
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if a news event likely occurred.
        
        Signs of news:
        - Sudden price jump/drop
        - Volume spike
        - Break from recent range
        
        Returns:
            Event info dict or None
        """
        if len(price_history) < 5:
            return None
        
        current_price = market_data.get("yes_price", 0.5)
        recent_prices = price_history[-5:]
        
        # Calculate recent range
        recent_high = max(recent_prices)
        recent_low = min(recent_prices)
        recent_range = recent_high - recent_low
        
        # Check for breakout
        if current_price > recent_high + recent_range:
            return {
                "type": "bullish_breakout",
                "magnitude": (current_price - recent_high) / recent_range,
                "timestamp": datetime.now()
            }
        
        if current_price < recent_low - recent_range:
            return {
                "type": "bearish_breakout",
                "magnitude": (recent_low - current_price) / recent_range,
                "timestamp": datetime.now()
            }
        
        # Check for sudden move within last observation
        if len(price_history) >= 2:
            last_move = abs(price_history[-1] - price_history[-2])
            avg_move = sum(abs(price_history[i] - price_history[i-1]) 
                         for i in range(1, len(price_history))) / (len(price_history) - 1)
            
            if last_move > avg_move * 3:
                direction = "bullish" if price_history[-1] > price_history[-2] else "bearish"
                return {
                    "type": f"{direction}_spike",
                    "magnitude": last_move / avg_move,
                    "timestamp": datetime.now()
                }
        
        return None
    
    def get_momentum_scores(self) -> Dict[str, Dict[str, Any]]:
        """
        Get momentum scores for all tracked markets.
        
        Returns:
            Dict mapping market_id to momentum metrics
        """
        scores = {}
        
        for market_id, history in self.price_history.items():
            if len(history) < 3:
                continue
            
            current = history[-1]
            momentum = self._calculate_momentum(
                market_id,
                current.price,
                current.volume
            )
            
            if momentum:
                price_change, volume_ratio, direction = momentum
                scores[market_id] = {
                    "price_change": price_change,
                    "volume_ratio": volume_ratio,
                    "direction": "UP" if direction > 0 else "DOWN" if direction < 0 else "FLAT",
                    "current_price": current.price,
                    "observations": len(history)
                }
        
        return scores


# Quick test
if __name__ == "__main__":
    strategy = MomentumStrategy()
    
    # Simulate price history
    market_id = "test_market"
    base_price = 0.50
    
    # Normal trading
    for i in range(10):
        strategy.update_price_history(
            market_id,
            base_price + (i * 0.005),  # Slow drift
            10000,
            datetime.now() - timedelta(minutes=60-i*5)
        )
    
    # Sudden spike (news event)
    strategy.update_price_history(
        market_id,
        0.65,  # 15% jump
        50000,  # Volume spike
        datetime.now()
    )
    
    test_market = {
        "market_id": market_id,
        "yes_price": 0.65,
        "no_price": 0.35,
        "volume_24h": 50000,
        "liquidity": 20000,
        "end_date": datetime.now() + timedelta(days=7)
    }
    
    signal = strategy.generate_signal(test_market)
    print(f"Signal after news spike: {signal.value}")
    print(f"Momentum scores: {strategy.get_momentum_scores()}")
