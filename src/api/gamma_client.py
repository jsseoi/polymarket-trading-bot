"""
Polymarket Gamma API Client

The Gamma API provides market discovery and metadata.
Endpoint: https://gamma-api.polymarket.com
"""

import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Market:
    """Represents a Polymarket prediction market."""
    condition_id: str
    question: str
    description: str
    end_date: Optional[datetime]
    outcomes: List[str]
    outcome_prices: List[float]
    volume: float
    liquidity: float
    active: bool
    closed: bool
    category: Optional[str]
    
    @property
    def spread(self) -> float:
        """Calculate bid-ask spread approximation."""
        if len(self.outcome_prices) >= 2:
            return abs(self.outcome_prices[0] + self.outcome_prices[1] - 1.0)
        return 0.0
    
    @property
    def implied_probability(self) -> Dict[str, float]:
        """Get implied probabilities for each outcome."""
        return dict(zip(self.outcomes, self.outcome_prices))


class GammaClient:
    """Client for Polymarket's Gamma API (market discovery)."""
    
    BASE_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, timeout: int = 30):
        self.session = requests.Session()
        self.timeout = timeout
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "polymarket-bot/1.0"
        })
    
    def get_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
        order: str = "volume",
        ascending: bool = False,
        tag: Optional[str] = None
    ) -> List[Market]:
        """
        Fetch markets from Gamma API.
        
        Args:
            active: Filter for active markets
            closed: Filter for closed markets
            limit: Number of results (max 100)
            offset: Pagination offset
            order: Sort field (volume, liquidity, end_date, created_at)
            ascending: Sort direction
            tag: Filter by category tag
            
        Returns:
            List of Market objects
        """
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": min(limit, 100),
            "offset": offset,
            "order": order,
            "ascending": str(ascending).lower(),
        }
        
        if tag:
            params["tag"] = tag
        
        response = self.session.get(
            f"{self.BASE_URL}/markets",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        markets = []
        for item in response.json():
            markets.append(self._parse_market(item))
        
        return markets
    
    def get_market(self, condition_id: str) -> Optional[Market]:
        """Fetch a single market by condition ID."""
        response = self.session.get(
            f"{self.BASE_URL}/markets/{condition_id}",
            timeout=self.timeout
        )
        
        if response.status_code == 404:
            return None
            
        response.raise_for_status()
        return self._parse_market(response.json())
    
    def search_markets(self, query: str, limit: int = 20) -> List[Market]:
        """
        Search markets by keyword.
        
        Args:
            query: Search term
            limit: Max results
            
        Returns:
            List of matching markets
        """
        params = {
            "q": query,
            "limit": limit
        }
        
        response = self.session.get(
            f"{self.BASE_URL}/markets",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        return [self._parse_market(m) for m in response.json()]
    
    def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch events (groups of related markets).
        
        Returns:
            List of event objects with their markets
        """
        params = {"limit": limit}
        
        response = self.session.get(
            f"{self.BASE_URL}/events",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        return response.json()
    
    def _parse_market(self, data: Dict[str, Any]) -> Market:
        """Parse API response into Market object."""
        
        # Parse end date
        end_date = None
        if data.get("end_date_iso"):
            try:
                end_date = datetime.fromisoformat(
                    data["end_date_iso"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        
        # Parse outcomes and prices
        outcomes = data.get("outcomes", ["Yes", "No"])
        if isinstance(outcomes, str):
            outcomes = outcomes.split(",")
        
        outcome_prices = []
        if "outcomePrices" in data:
            prices = data["outcomePrices"]
            if isinstance(prices, str):
                outcome_prices = [float(p) for p in prices.split(",")]
            elif isinstance(prices, list):
                outcome_prices = [float(p) for p in prices]
        
        return Market(
            condition_id=data.get("condition_id", data.get("id", "")),
            question=data.get("question", ""),
            description=data.get("description", ""),
            end_date=end_date,
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            volume=float(data.get("volume", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            active=data.get("active", False),
            closed=data.get("closed", False),
            category=data.get("category")
        )


# Quick test
if __name__ == "__main__":
    client = GammaClient()
    
    print("Fetching top markets by volume...")
    markets = client.get_markets(limit=5)
    
    for m in markets:
        print(f"\n{m.question}")
        print(f"  Volume: ${m.volume:,.0f}")
        print(f"  Prices: {m.implied_probability}")
        print(f"  Spread: {m.spread:.2%}")
