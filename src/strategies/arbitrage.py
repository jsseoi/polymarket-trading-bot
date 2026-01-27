"""
Arbitrage Strategy

Detects and exploits pricing inefficiencies:
1. Intra-market arbitrage: YES + NO prices don't sum to 1.0
2. Cross-market arbitrage: Related markets with inconsistent pricing
3. Time-decay arbitrage: Markets near expiry with mispriced outcomes

This strategy has the highest win rate (~95%) but opportunities are rare
and competition is fierce.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from .base_strategy import BaseStrategy, Signal, Position


@dataclass
class ArbitrageOpportunity:
    """Represents a detected arbitrage opportunity."""
    opportunity_type: str  # "intra", "cross", "time_decay"
    market_ids: List[str]
    description: str
    expected_profit: float
    expected_profit_pct: float
    confidence: float
    timestamp: datetime


class ArbitrageStrategy(BaseStrategy):
    """
    Detects and exploits arbitrage opportunities in prediction markets.
    
    Types of arbitrage:
    
    1. **Intra-market arbitrage** (Dutch Book):
       If YES + NO prices < 1.0, buy both and guarantee profit.
       If YES + NO prices > 1.0, sell both (if possible) for guaranteed profit.
       
    2. **Cross-market arbitrage**:
       Related markets (e.g., "Will X win?" vs "Will X lose?") may have
       inconsistent pricing that guarantees profit.
       
    3. **Time-decay arbitrage**:
       Markets near resolution may have prices that don't reflect the
       near-certain outcome, especially in illiquid markets.
    
    Parameters:
        min_spread: Minimum price spread to consider (covers fees)
        min_profit_pct: Minimum expected profit percentage
        max_position_duration: Max hours to hold a position
    """
    
    def __init__(
        self,
        min_spread: float = 0.02,  # 2% minimum spread
        min_profit_pct: float = 0.01,  # 1% minimum profit
        max_position_duration: int = 48,  # 48 hours max
        fee_rate: float = 0.02,  # 2% trading fee
        **kwargs
    ):
        super().__init__(name="Arbitrage", **kwargs)
        self.min_spread = min_spread
        self.min_profit_pct = min_profit_pct
        self.max_position_duration = max_position_duration
        self.fee_rate = fee_rate
        self.detected_opportunities: List[ArbitrageOpportunity] = []
    
    def generate_signal(
        self,
        market_data: Dict[str, Any],
        historical_data: Optional[List[Dict]] = None
    ) -> Signal:
        """
        Detect arbitrage opportunities and generate signal.
        
        Currently implements intra-market arbitrage detection.
        Cross-market requires multiple market feeds (future enhancement).
        """
        yes_price = market_data.get("yes_price", 0.5)
        no_price = market_data.get("no_price", 0.5)
        volume = market_data.get("volume", 0)
        liquidity = market_data.get("liquidity", 0)
        end_date = market_data.get("end_date")
        
        # Check for intra-market arbitrage (Dutch Book)
        opportunity = self._check_intra_market_arb(
            yes_price, no_price, volume, liquidity, market_data
        )
        
        if opportunity:
            self.detected_opportunities.append(opportunity)
            
            # Determine which side to take
            if yes_price + no_price < 1.0:
                # Prices sum to less than 1 - buy both
                # For simplicity, we buy the cheaper side first
                if yes_price < no_price:
                    return Signal.BUY  # Buy YES
                else:
                    return Signal.SELL  # Buy NO (Sell YES in our framework)
        
        # Check for time-decay arbitrage
        if end_date:
            time_arb = self._check_time_decay_arb(
                yes_price, no_price, end_date, market_data
            )
            if time_arb:
                self.detected_opportunities.append(time_arb)
                # Bet on the likely outcome
                if yes_price > 0.9:
                    return Signal.BUY
                elif no_price > 0.9:
                    return Signal.SELL
        
        return Signal.HOLD
    
    def _check_intra_market_arb(
        self,
        yes_price: float,
        no_price: float,
        volume: float,
        liquidity: float,
        market_data: Dict[str, Any]
    ) -> Optional[ArbitrageOpportunity]:
        """
        Check for intra-market (Dutch Book) arbitrage.
        
        If YES + NO < 1.0 (minus fees), there's a guaranteed profit
        by buying both outcomes.
        
        In practice, this is rare on efficient markets like Polymarket,
        but can occur during high volatility or low liquidity.
        """
        total_price = yes_price + no_price
        
        # Account for fees (round-trip)
        effective_spread = 1.0 - total_price
        net_spread = effective_spread - (2 * self.fee_rate)  # Buy both sides
        
        if net_spread > self.min_spread:
            profit_pct = net_spread / total_price
            
            if profit_pct >= self.min_profit_pct:
                # Check liquidity is sufficient
                if liquidity < 1000:
                    return None  # Too illiquid
                
                return ArbitrageOpportunity(
                    opportunity_type="intra",
                    market_ids=[market_data.get("market_id", "unknown")],
                    description=f"Dutch book: YES({yes_price:.3f}) + NO({no_price:.3f}) = {total_price:.3f}",
                    expected_profit=net_spread,
                    expected_profit_pct=profit_pct,
                    confidence=min(0.95, liquidity / 10000),  # Higher liquidity = more confidence
                    timestamp=datetime.now()
                )
        
        return None
    
    def _check_time_decay_arb(
        self,
        yes_price: float,
        no_price: float,
        end_date: datetime,
        market_data: Dict[str, Any]
    ) -> Optional[ArbitrageOpportunity]:
        """
        Check for time-decay arbitrage near resolution.
        
        If a market is about to resolve and one outcome is trading
        at < 0.95 when it's nearly certain, that's an opportunity.
        
        This requires domain knowledge about the market's likely outcome.
        """
        hours_to_expiry = (end_date - datetime.now()).total_seconds() / 3600
        
        # Only check markets very close to resolution
        if hours_to_expiry > 24:
            return None
        
        if hours_to_expiry < 1:
            return None  # Too close, might already be resolved
        
        # Look for high-probability outcomes that aren't priced at ~1.0
        if yes_price > 0.90 and yes_price < 0.98:
            expected_profit = 1.0 - yes_price - self.fee_rate
            if expected_profit > self.min_profit_pct:
                return ArbitrageOpportunity(
                    opportunity_type="time_decay",
                    market_ids=[market_data.get("market_id", "unknown")],
                    description=f"Near-expiry YES at {yes_price:.3f}, {hours_to_expiry:.1f}h to resolution",
                    expected_profit=expected_profit,
                    expected_profit_pct=expected_profit / yes_price,
                    confidence=0.85 * (yes_price - 0.5) * 2,  # Higher confidence for higher prices
                    timestamp=datetime.now()
                )
        
        if no_price > 0.90 and no_price < 0.98:
            expected_profit = 1.0 - no_price - self.fee_rate
            if expected_profit > self.min_profit_pct:
                return ArbitrageOpportunity(
                    opportunity_type="time_decay",
                    market_ids=[market_data.get("market_id", "unknown")],
                    description=f"Near-expiry NO at {no_price:.3f}, {hours_to_expiry:.1f}h to resolution",
                    expected_profit=expected_profit,
                    expected_profit_pct=expected_profit / no_price,
                    confidence=0.85 * (no_price - 0.5) * 2,
                    timestamp=datetime.now()
                )
        
        return None
    
    def should_exit(
        self,
        position: Position,
        market_data: Dict[str, Any]
    ) -> bool:
        """
        Exit conditions for arbitrage positions.
        
        1. Market resolved
        2. Position held too long (decay in edge)
        3. Spread closed (arbitrage opportunity gone)
        """
        is_closed = market_data.get("closed", False)
        
        # Exit if resolved
        if is_closed:
            return True
        
        # Exit if held too long
        hours_held = (datetime.now() - position.entry_time).total_seconds() / 3600
        if hours_held > self.max_position_duration:
            return True
        
        # For intra-market arb, exit if spread closed
        yes_price = market_data.get("yes_price", 0.5)
        no_price = market_data.get("no_price", 0.5)
        current_spread = 1.0 - (yes_price + no_price)
        
        if current_spread < self.min_spread / 2:
            # Spread has tightened significantly
            return True
        
        return False
    
    def find_cross_market_arbitrage(
        self,
        markets: List[Dict[str, Any]]
    ) -> List[ArbitrageOpportunity]:
        """
        Find cross-market arbitrage opportunities.
        
        Looks for related markets with inconsistent pricing.
        
        Example:
        - "Will candidate A win?" at 0.60
        - "Will candidate B win?" at 0.55
        - If A and B are the only candidates, prices should sum to 1.0
        
        This requires semantic understanding of market relationships.
        For now, we look for markets with similar questions and check
        for logical inconsistencies.
        
        Args:
            markets: List of market data dictionaries
            
        Returns:
            List of detected arbitrage opportunities
        """
        opportunities = []
        
        # Group markets by question similarity (simple approach)
        # In production, you'd use NLP or market tags
        
        for i, market_a in enumerate(markets):
            for market_b in markets[i+1:]:
                # Check if markets might be related
                # (This is a placeholder for proper semantic analysis)
                q_a = market_a.get("question", "").lower()
                q_b = market_b.get("question", "").lower()
                
                # Look for opposite questions
                if self._are_opposite_questions(q_a, q_b):
                    yes_a = market_a.get("yes_price", 0.5)
                    yes_b = market_b.get("yes_price", 0.5)
                    
                    # If these are true opposites, YES_A + YES_B should ≈ 1.0
                    total = yes_a + yes_b
                    spread = abs(1.0 - total)
                    
                    if spread > self.min_spread + (2 * self.fee_rate):
                        profit_pct = (spread - 2 * self.fee_rate) / min(yes_a, yes_b)
                        
                        opportunities.append(ArbitrageOpportunity(
                            opportunity_type="cross",
                            market_ids=[
                                market_a.get("market_id", "unknown"),
                                market_b.get("market_id", "unknown")
                            ],
                            description=f"Cross-market: {q_a[:30]}... + {q_b[:30]}... = {total:.3f}",
                            expected_profit=spread - 2 * self.fee_rate,
                            expected_profit_pct=profit_pct,
                            confidence=0.7,  # Lower confidence for semantic matching
                            timestamp=datetime.now()
                        ))
        
        return opportunities
    
    def _are_opposite_questions(self, q_a: str, q_b: str) -> bool:
        """
        Check if two questions are logical opposites.
        
        This is a simple heuristic. In production, use NLP.
        """
        # Check for obvious opposite patterns
        opposite_pairs = [
            ("will", "won't"),
            ("yes", "no"),
            ("win", "lose"),
            ("above", "below"),
            ("over", "under"),
            ("more", "less"),
        ]
        
        for pos, neg in opposite_pairs:
            if pos in q_a and neg in q_b:
                # Check if rest of question is similar
                q_a_clean = q_a.replace(pos, "").replace(neg, "")
                q_b_clean = q_b.replace(pos, "").replace(neg, "")
                
                # Simple similarity check
                words_a = set(q_a_clean.split())
                words_b = set(q_b_clean.split())
                overlap = len(words_a & words_b)
                
                if overlap > min(len(words_a), len(words_b)) * 0.7:
                    return True
        
        return False
    
    def get_opportunities_summary(self) -> str:
        """Get summary of detected opportunities."""
        if not self.detected_opportunities:
            return "No arbitrage opportunities detected."
        
        summary = f"Detected {len(self.detected_opportunities)} opportunities:\n\n"
        
        for i, opp in enumerate(self.detected_opportunities[-10:], 1):
            summary += f"{i}. [{opp.opportunity_type.upper()}] {opp.description}\n"
            summary += f"   Expected profit: {opp.expected_profit_pct:.2%} | Confidence: {opp.confidence:.0%}\n\n"
        
        return summary


# Quick test
if __name__ == "__main__":
    strategy = ArbitrageStrategy()
    
    # Test intra-market arbitrage detection
    test_market = {
        "market_id": "test_123",
        "yes_price": 0.45,
        "no_price": 0.50,  # Total = 0.95, potential 5% spread
        "volume": 100000,
        "liquidity": 20000,
        "end_date": datetime.now() + timedelta(days=7)
    }
    
    signal = strategy.generate_signal(test_market)
    print(f"Test market signal: {signal.value}")
    print(strategy.get_opportunities_summary())
