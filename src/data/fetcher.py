"""
Historical Data Fetcher

Fetches and caches historical market data from Polymarket APIs
for backtesting purposes.
"""

import json
import time
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict

import requests


@dataclass
class HistoricalSnapshot:
    """A point-in-time snapshot of market state."""
    timestamp: str
    market_id: str
    question: str
    yes_price: float
    no_price: float
    volume: float
    volume_24h: float
    liquidity: float
    end_date: Optional[str]
    resolved: bool
    resolution: Optional[str]


class DataFetcher:
    """
    Fetches historical market data from Polymarket.
    
    Data sources:
    1. Gamma API - Market metadata and current state
    2. CLOB API - Historical trades and order book snapshots
    3. Archived data - Historical resolved markets
    
    Usage:
        fetcher = DataFetcher(cache_dir="data/cache")
        
        # Fetch active markets
        markets = fetcher.fetch_markets(limit=100)
        
        # Fetch historical trades for a market
        trades = fetcher.fetch_trades(market_id, days=30)
        
        # Build historical snapshots
        snapshots = fetcher.build_historical_snapshots(days=90)
        
        # Save for backtesting
        fetcher.save_snapshots(snapshots, "data/historical.json")
    """
    
    GAMMA_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"
    
    def __init__(
        self,
        cache_dir: str = "data/cache",
        rate_limit_delay: float = 0.5
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit_delay = rate_limit_delay
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "polymarket-bot/1.0"
        })
    
    def fetch_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetch markets from Gamma API.
        
        Args:
            active: Include active markets
            closed: Include closed/resolved markets
            limit: Number of markets to fetch
            offset: Pagination offset
            
        Returns:
            List of market dictionaries
        """
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": min(limit, 100),
            "offset": offset
        }
        
        response = self.session.get(
            f"{self.GAMMA_URL}/markets",
            params=params,
            timeout=30
        )
        response.raise_for_status()
        
        time.sleep(self.rate_limit_delay)
        return response.json()
    
    def fetch_all_markets(
        self,
        include_closed: bool = True,
        max_markets: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Fetch all available markets with pagination.
        
        Args:
            include_closed: Whether to include resolved markets
            max_markets: Maximum number of markets to fetch
            
        Returns:
            List of all markets
        """
        all_markets = []
        offset = 0
        batch_size = 100
        
        while len(all_markets) < max_markets:
            # Fetch active markets
            active = self.fetch_markets(
                active=True,
                closed=False,
                limit=batch_size,
                offset=offset
            )
            
            if not active:
                break
            
            all_markets.extend(active)
            offset += batch_size
            
            print(f"Fetched {len(all_markets)} markets...")
        
        if include_closed:
            offset = 0
            while len(all_markets) < max_markets:
                closed = self.fetch_markets(
                    active=False,
                    closed=True,
                    limit=batch_size,
                    offset=offset
                )
                
                if not closed:
                    break
                
                all_markets.extend(closed)
                offset += batch_size
                
                print(f"Fetched {len(all_markets)} markets (including closed)...")
        
        return all_markets[:max_markets]
    
    def fetch_trades(
        self,
        token_id: str,
        limit: int = 500,
        before: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent trades for a token from CLOB API.
        
        Args:
            token_id: The token's contract address
            limit: Maximum trades to fetch
            before: Fetch trades before this timestamp
            
        Returns:
            List of trade dictionaries
        """
        params = {
            "token_id": token_id,
            "limit": min(limit, 500)
        }
        
        if before:
            params["before"] = before
        
        try:
            response = self.session.get(
                f"{self.CLOB_URL}/trades",
                params=params,
                timeout=30
            )
            response.raise_for_status()
            time.sleep(self.rate_limit_delay)
            return response.json()
        except Exception as e:
            print(f"Error fetching trades for {token_id}: {e}")
            return []
    
    def fetch_order_book(self, token_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch current order book for a token.
        
        Args:
            token_id: The token's contract address
            
        Returns:
            Order book dictionary or None
        """
        try:
            response = self.session.get(
                f"{self.CLOB_URL}/book",
                params={"token_id": token_id},
                timeout=30
            )
            response.raise_for_status()
            time.sleep(self.rate_limit_delay)
            return response.json()
        except Exception as e:
            print(f"Error fetching order book for {token_id}: {e}")
            return None
    
    def build_historical_snapshots(
        self,
        days: int = 90,
        markets: Optional[List[Dict]] = None,
        snapshots_per_day: int = 4
    ) -> List[HistoricalSnapshot]:
        """
        Build historical snapshots from trade data.
        
        This reconstructs historical market states from trade history.
        For each market, we sample the price at regular intervals
        based on the trades that occurred.
        
        Args:
            days: Number of days of history to build
            markets: Markets to process (fetches if not provided)
            snapshots_per_day: How many snapshots per day
            
        Returns:
            List of HistoricalSnapshot objects
        """
        if markets is None:
            print("Fetching markets...")
            markets = self.fetch_all_markets(include_closed=True, max_markets=200)
        
        snapshots = []
        start_date = datetime.now() - timedelta(days=days)
        
        for i, market in enumerate(markets):
            market_id = market.get("condition_id", market.get("id", ""))
            question = market.get("question", "Unknown")
            
            print(f"Processing market {i+1}/{len(markets)}: {question[:50]}...")
            
            # Get token IDs for YES/NO outcomes
            tokens = market.get("tokens", [])
            if len(tokens) < 2:
                # Try to get from clobTokenIds
                clob_ids = market.get("clobTokenIds", "").split(",")
                if len(clob_ids) >= 2:
                    tokens = [{"token_id": clob_ids[0]}, {"token_id": clob_ids[1]}]
                else:
                    continue
            
            yes_token = tokens[0].get("token_id", "")
            
            if not yes_token:
                continue
            
            # Fetch trades
            trades = self.fetch_trades(yes_token, limit=500)
            
            if not trades:
                # No trade data, create snapshot from current prices
                yes_price = float(market.get("outcomePrices", "0.5,0.5").split(",")[0])
                no_price = 1.0 - yes_price
                
                snapshots.append(HistoricalSnapshot(
                    timestamp=datetime.now().isoformat(),
                    market_id=market_id,
                    question=question,
                    yes_price=yes_price,
                    no_price=no_price,
                    volume=float(market.get("volume", 0) or 0),
                    volume_24h=float(market.get("volume24hr", 0) or 0),
                    liquidity=float(market.get("liquidity", 0) or 0),
                    end_date=market.get("end_date_iso"),
                    resolved=market.get("closed", False),
                    resolution=market.get("resolution")
                ))
                continue
            
            # Build price history from trades
            price_history = self._build_price_history(trades, start_date, snapshots_per_day)
            
            for ts, price in price_history:
                snapshots.append(HistoricalSnapshot(
                    timestamp=ts.isoformat(),
                    market_id=market_id,
                    question=question,
                    yes_price=price,
                    no_price=1.0 - price,
                    volume=float(market.get("volume", 0) or 0),
                    volume_24h=float(market.get("volume24hr", 0) or 0),
                    liquidity=float(market.get("liquidity", 0) or 0),
                    end_date=market.get("end_date_iso"),
                    resolved=market.get("closed", False),
                    resolution=market.get("resolution")
                ))
        
        # Sort by timestamp
        snapshots.sort(key=lambda x: x.timestamp)
        
        return snapshots
    
    def _build_price_history(
        self,
        trades: List[Dict],
        start_date: datetime,
        snapshots_per_day: int
    ) -> List[tuple]:
        """
        Build price history from trades.
        
        Args:
            trades: List of trade dictionaries
            start_date: Start of history window
            snapshots_per_day: Snapshots per day
            
        Returns:
            List of (timestamp, price) tuples
        """
        if not trades:
            return []
        
        # Sort trades by timestamp
        sorted_trades = sorted(trades, key=lambda x: x.get("timestamp", 0))
        
        # Filter to date range
        start_ts = int(start_date.timestamp() * 1000)
        filtered = [t for t in sorted_trades if t.get("timestamp", 0) >= start_ts]
        
        if not filtered:
            # Use most recent trade price
            latest = sorted_trades[-1]
            return [(datetime.now(), float(latest.get("price", 0.5)))]
        
        # Sample at regular intervals
        interval_hours = 24 // snapshots_per_day
        history = []
        
        current_time = start_date
        end_time = datetime.now()
        trade_idx = 0
        current_price = float(filtered[0].get("price", 0.5))
        
        while current_time < end_time:
            current_ts = int(current_time.timestamp() * 1000)
            
            # Find most recent trade before this timestamp
            while trade_idx < len(filtered) - 1:
                next_ts = filtered[trade_idx + 1].get("timestamp", 0)
                if next_ts > current_ts:
                    break
                trade_idx += 1
                current_price = float(filtered[trade_idx].get("price", current_price))
            
            history.append((current_time, current_price))
            current_time += timedelta(hours=interval_hours)
        
        return history
    
    def save_snapshots(
        self,
        snapshots: List[HistoricalSnapshot],
        filepath: str
    ) -> int:
        """
        Save snapshots to JSON file for backtesting.
        
        Args:
            snapshots: List of HistoricalSnapshot objects
            filepath: Output file path
            
        Returns:
            Number of snapshots saved
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = [asdict(s) for s in snapshots]
        
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"Saved {len(data)} snapshots to {filepath}")
        return len(data)
    
    def load_snapshots(self, filepath: str) -> List[HistoricalSnapshot]:
        """
        Load snapshots from JSON file.
        
        Args:
            filepath: Input file path
            
        Returns:
            List of HistoricalSnapshot objects
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        return [HistoricalSnapshot(**item) for item in data]
    
    def get_cache_path(self, key: str) -> Path:
        """Get cache file path for a key."""
        return self.cache_dir / f"{key}.json"
    
    def cache_data(self, key: str, data: Any) -> None:
        """Cache data to disk."""
        path = self.get_cache_path(key)
        with open(path, 'w') as f:
            json.dump(data, f)
    
    def load_cache(self, key: str, max_age_hours: int = 24) -> Optional[Any]:
        """
        Load cached data if fresh enough.
        
        Args:
            key: Cache key
            max_age_hours: Maximum cache age in hours
            
        Returns:
            Cached data or None if stale/missing
        """
        path = self.get_cache_path(key)
        
        if not path.exists():
            return None
        
        # Check age
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        age = datetime.now() - mtime
        
        if age > timedelta(hours=max_age_hours):
            return None
        
        with open(path, 'r') as f:
            return json.load(f)


# CLI interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Fetch Polymarket historical data")
    parser.add_argument("--output", default="data/historical.json", help="Output file")
    parser.add_argument("--days", type=int, default=90, help="Days of history")
    parser.add_argument("--max-markets", type=int, default=100, help="Max markets to fetch")
    parser.add_argument("--cache-dir", default="data/cache", help="Cache directory")
    
    args = parser.parse_args()
    
    fetcher = DataFetcher(cache_dir=args.cache_dir)
    
    print(f"Fetching up to {args.max_markets} markets...")
    markets = fetcher.fetch_all_markets(
        include_closed=True,
        max_markets=args.max_markets
    )
    print(f"Found {len(markets)} markets")
    
    print(f"\nBuilding {args.days} days of historical snapshots...")
    snapshots = fetcher.build_historical_snapshots(
        days=args.days,
        markets=markets
    )
    
    print(f"\nSaving {len(snapshots)} snapshots...")
    fetcher.save_snapshots(snapshots, args.output)
    
    print("Done!")
