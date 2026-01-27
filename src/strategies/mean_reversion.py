"""
Mean Reversion Strategy

Trades based on the principle that prices tend to revert to their mean.

Core insight: Prediction markets often overreact to news, pushing prices
away from fair value. Prices then gradually revert as the market digests
the information and noise traders exit.

This strategy:
1. Calculates rolling average price (the "mean")
2. Identifies when current price deviates significantly from mean
3. Bets on reversion to the mean
4. Uses Bollinger Band-style thresholds

Research shows mean reversion works best on:
- High-volume political markets
- Markets with stable fundamentals
- Longer time horizons (days/weeks)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import deque
import math
from .base_strategy import BaseStrategy, Signal, Position


@dataclass
class PriceStats:
    """Rolling statistics for a market."""
    mean: float
    std: float
    upper_band: float
    lower_band: float
    z_score: float
    observations: int


class MeanReversionStrategy(BaseStrategy):
    """
    Mean reversion strategy using Bollinger Band principles.
    
    When prices deviate beyond N standard deviations from the rolling mean,
    we bet on reversion to the mean.
    
    Parameters:
        lookback_periods: Number of observations for rolling statistics
        entry_z_threshold: Z-score threshold to enter (default 2.0 = 2 std devs)
        exit_z_threshold: Z-score to exit (default 0.5 = near mean)
        min_volatility: Minimum std dev to trade (avoid flat markets)
        max_position_time: Max hours to hold before forced exit
    """
    
    def __init__(
        self,
        lookback_periods: int = 20,
        entry_z_threshold: float = 2.0,
        exit_z_threshold: float = 0.5,
        min_volatility: float = 0.02,
        max_position_time: int = 72,  # 3 days
        **kwargs
    ):
        super().__init__(name="MeanReversion", **kwargs)
        self.lookback_periods = lookback_periods
        self.entry_z_threshold = entry_z_threshold
        self.exit_z_threshold = exit_z_threshold
        self.min_volatility = min_volatility
        self.max_position_time = max_position_time
        
        # Price history per market
        self.price_history: Dict[str, deque] = {}
    
    def update_price_history(
        self,
        market_id: str,
        price: float,
        timestamp: Optional[datetime] = None
    ) -> None:
        """
        Update price history for a market.
        
        Should be called with each new price observation.
        """
        if market_id not in self.price_history:
            self.price_history[market_id] = deque(maxlen=self.lookback_periods * 2)
        
        self.price_history[market_id].append({
            'price': price,
            'timestamp': timestamp or datetime.now()
        })
    
    def calculate_stats(self, market_id: str, current_price: float) -> Optional[PriceStats]:
        """
        Calculate rolling statistics for a market.
        
        Returns:
            PriceStats with mean, std, bands, and z-score, or None if insufficient data
        """
        history = self.price_history.get(market_id)
        
        if not history or len(history) < self.lookback_periods:
            return None
        
        # Get recent prices
        prices = [p['price'] for p in list(history)[-self.lookback_periods:]]
        
        # Calculate mean
        mean = sum(prices) / len(prices)
        
        # Calculate standard deviation
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std = math.sqrt(variance) if variance > 0 else 0.001
        
        # Calculate Bollinger Bands (2 std devs)
        upper_band = mean + (2 * std)
        lower_band = mean - (2 * std)
        
        # Calculate z-score of current price
        z_score = (current_price - mean) / std if std > 0 else 0
        
        return PriceStats(
            mean=mean,
            std=std,
            upper_band=upper_band,
            lower_band=lower_band,
            z_score=z_score,
            observations=len(prices)
        )
    
    def generate_signal(
        self,
        market_data: Dict[str, Any],
        historical_data: Optional[List[Dict]] = None
    ) -> Signal:
        """
        Generate signal based on mean reversion.
        
        Buy when price is significantly below mean (oversold).
        Sell when price is significantly above mean (overbought).
        """
        market_id = market_data.get("market_id", "")
        yes_price = market_data.get("yes_price", 0.5)
        volume = market_data.get("volume", 0)
        liquidity = market_data.get("liquidity", 0)
        end_date = market_data.get("end_date")
        
        # Filter: Need sufficient liquidity
        if liquidity < 10000:
            return Signal.HOLD
        
        # Filter: Don't trade near expiry (mean reversion needs time)
        if end_date:
            days_to_expiry = (end_date - datetime.now()).days
            if days_to_expiry < 7:  # Need at least a week
                return Signal.HOLD
        
        # Update history if we have historical data
        if historical_data:
            for point in historical_data[-self.lookback_periods * 2:]:
                self.update_price_history(
                    market_id,
                    point.get("yes_price", 0.5),
                    datetime.fromisoformat(point["timestamp"]) if "timestamp" in point else None
                )
        
        # Also update with current price
        self.update_price_history(market_id, yes_price)
        
        # Calculate statistics
        stats = self.calculate_stats(market_id, yes_price)
        
        if not stats:
            return Signal.HOLD
        
        # Check for minimum volatility
        if stats.std < self.min_volatility:
            return Signal.HOLD
        
        # Mean reversion logic
        if stats.z_score <= -self.entry_z_threshold:
            # Price is significantly below mean - oversold
            # Expect reversion UP, so buy YES
            return Signal.BUY
        
        if stats.z_score >= self.entry_z_threshold:
            # Price is significantly above mean - overbought
            # Expect reversion DOWN, so buy NO (sell YES)
            return Signal.SELL
        
        return Signal.HOLD
    
    def should_exit(
        self,
        position: Position,
        market_data: Dict[str, Any]
    ) -> bool:
        """
        Exit conditions for mean reversion trades.
        
        1. Market resolved
        2. Price reverted to mean (target achieved)
        3. Position held too long (mean may have shifted)
        4. Z-score reversed significantly (mean shift)
        """
        is_closed = market_data.get("closed", False)
        current_price = market_data.get("yes_price", 0.5)
        market_id = market_data.get("market_id", "")
        
        # Exit if resolved
        if is_closed:
            return True
        
        # Exit if held too long
        hours_held = (datetime.now() - position.entry_time).total_seconds() / 3600
        if hours_held > self.max_position_time:
            return True
        
        # Calculate current stats
        stats = self.calculate_stats(market_id, current_price)
        
        if not stats:
            return False  # Keep position if no stats
        
        # Exit when reverted to mean
        if abs(stats.z_score) <= self.exit_z_threshold:
            return True
        
        # Exit if trade went wrong (z-score increased in wrong direction)
        if position.side == "YES":
            # We bought YES expecting price to rise (z was negative)
            # If z-score becomes even more negative, our thesis is wrong
            if stats.z_score <= -3.0:
                return True  # Stop loss - further deviation
        else:
            # We bought NO expecting price to fall (z was positive)
            if stats.z_score >= 3.0:
                return True
        
        return False
    
    def get_market_analysis(self, market_id: str, current_price: float) -> Dict[str, Any]:
        """
        Get detailed analysis for a market.
        
        Useful for understanding current market state.
        """
        stats = self.calculate_stats(market_id, current_price)
        
        if not stats:
            return {
                "market_id": market_id,
                "status": "insufficient_data",
                "message": f"Need {self.lookback_periods} observations"
            }
        
        # Determine regime
        if stats.z_score >= self.entry_z_threshold:
            regime = "OVERBOUGHT"
            action = "Sell YES (buy NO)"
        elif stats.z_score <= -self.entry_z_threshold:
            regime = "OVERSOLD"
            action = "Buy YES"
        elif abs(stats.z_score) <= self.exit_z_threshold:
            regime = "FAIR_VALUE"
            action = "Hold"
        else:
            regime = "NEUTRAL"
            action = "Wait for better entry"
        
        return {
            "market_id": market_id,
            "current_price": current_price,
            "mean": round(stats.mean, 4),
            "std": round(stats.std, 4),
            "z_score": round(stats.z_score, 2),
            "upper_band": round(stats.upper_band, 4),
            "lower_band": round(stats.lower_band, 4),
            "regime": regime,
            "suggested_action": action,
            "observations": stats.observations,
            "entry_threshold": self.entry_z_threshold,
            "exit_threshold": self.exit_z_threshold
        }
    
    def scan_markets(
        self,
        markets: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Scan multiple markets for mean reversion opportunities.
        
        Returns markets sorted by absolute z-score (best opportunities first).
        """
        opportunities = []
        
        for market in markets:
            market_id = market.get("market_id", market.get("condition_id", ""))
            yes_price = market.get("yes_price", 0.5)
            
            if not yes_price:
                prices = market.get("outcomePrices", "0.5,0.5").split(",")
                yes_price = float(prices[0]) if prices else 0.5
            
            analysis = self.get_market_analysis(market_id, yes_price)
            
            if analysis.get("status") == "insufficient_data":
                continue
            
            if analysis.get("regime") in ["OVERBOUGHT", "OVERSOLD"]:
                opportunities.append({
                    **analysis,
                    "question": market.get("question", "")[:50],
                    "volume": market.get("volume", 0),
                    "liquidity": market.get("liquidity", 0)
                })
        
        # Sort by absolute z-score
        opportunities.sort(key=lambda x: abs(x.get("z_score", 0)), reverse=True)
        
        return opportunities


# Quick test
if __name__ == "__main__":
    import random
    
    strategy = MeanReversionStrategy(lookback_periods=10)
    
    # Simulate price history with mean reversion properties
    market_id = "test_market"
    base_price = 0.50
    
    # Generate mean-reverting random walk
    price = base_price
    for i in range(20):
        # Mean-reverting component
        reversion = (base_price - price) * 0.2
        # Random shock
        shock = random.gauss(0, 0.03)
        price = max(0.1, min(0.9, price + reversion + shock))
        
        strategy.update_price_history(
            market_id,
            price,
            datetime.now() - timedelta(hours=20-i)
        )
    
    # Current price is 2 std devs below mean
    current_price = 0.35
    strategy.update_price_history(market_id, current_price)
    
    test_market = {
        "market_id": market_id,
        "yes_price": current_price,
        "no_price": 1 - current_price,
        "volume": 100000,
        "liquidity": 25000,
        "end_date": datetime.now() + timedelta(days=30)
    }
    
    signal = strategy.generate_signal(test_market)
    analysis = strategy.get_market_analysis(market_id, current_price)
    
    print(f"Current price: {current_price}")
    print(f"Analysis: {analysis}")
    print(f"Signal: {signal.value}")
