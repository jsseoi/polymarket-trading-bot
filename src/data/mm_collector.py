"""
Market Making Data Collector

Extended data collection for market-making backtests.
Adds:
- CLOB /prices-history endpoint (hourly candles)
- archive.pmxt.dev orderbook snapshots (Parquet)
- Market selection filters for MM suitability
- Conversion to backtest engine JSON format
"""

import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict

import requests
import pandas as pd

from .fetcher import DataFetcher, HistoricalSnapshot


@dataclass
class MarketInfo:
    """Filtered market suitable for market-making."""
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    end_date: Optional[str]
    volume: float
    volume_24h: float
    liquidity: float
    category: Optional[str]
    active: bool
    closed: bool
    resolution: Optional[str]


class MMDataCollector(DataFetcher):
    """
    Data collector specialized for market-making backtests.

    Extends DataFetcher with:
    - Price history from CLOB /prices-history (hourly resolution)
    - Market filtering (min volume, liquidity, duration)
    - Efficient batch collection for multiple markets
    - Parquet orderbook snapshot loading from archive.pmxt.dev

    Usage:
        collector = MMDataCollector()

        # Find suitable markets
        markets = collector.find_mm_markets(min_volume_24h=10000, min_liquidity=5000)

        # Collect price history
        snapshots = collector.collect_price_history(markets, days=90)

        # Save for backtesting
        collector.save_snapshots(snapshots, "data/mm_historical.json")
    """

    CLOB_PRICES_URL = "https://clob.polymarket.com/prices-history"
    ARCHIVE_BASE_URL = "https://archive.pmxt.dev/Polymarket"

    def find_mm_markets(
        self,
        min_volume_24h: float = 10_000,
        min_liquidity: float = 5_000,
        min_days_to_expiry: int = 7,
        max_markets: int = 50,
        categories: Optional[List[str]] = None,
    ) -> List[MarketInfo]:
        """
        Find markets suitable for market-making.

        Filters:
        - Minimum 24h volume and liquidity
        - At least N days until expiry (need time for MM to operate)
        - Active, not resolved
        - Optionally filter by category (politics, crypto, etc.)
        """
        import json as _json

        # Fetch large pool, then filter down
        all_raw = self.fetch_all_markets(include_closed=False, max_markets=1000)

        now = datetime.now()
        suitable = []

        for m in all_raw:
            # Parse basic fields (API returns camelCase)
            volume_24h = float(m.get("volume24hr", m.get("volume24hrClob", 0)) or 0)
            liquidity = float(m.get("liquidityClob", m.get("liquidity", 0)) or 0)
            volume = float(m.get("volumeClob", m.get("volume", 0)) or 0)
            active = m.get("active", False)
            closed = m.get("closed", False)

            if closed or not active:
                continue
            if volume_24h < min_volume_24h:
                continue
            if liquidity < min_liquidity:
                continue

            # Check expiry (API returns endDateIso or endDate)
            end_date_str = m.get("endDateIso") or m.get("endDate") or m.get("end_date_iso")
            if end_date_str:
                try:
                    # endDateIso is often just "YYYY-MM-DD", endDate has timezone
                    cleaned = end_date_str.replace("Z", "+00:00")
                    if "T" not in cleaned and len(cleaned) == 10:
                        cleaned += "T00:00:00+00:00"
                    end_date = datetime.fromisoformat(cleaned)
                    end_naive = end_date.replace(tzinfo=None)
                    days_to_expiry = (end_naive - now).days
                    if days_to_expiry < min_days_to_expiry:
                        continue
                except (ValueError, TypeError):
                    pass

            # Category filter
            category = m.get("category") or m.get("groupItemTitle")
            if categories and category and category.lower() not in [c.lower() for c in categories]:
                continue

            # Extract token IDs (clobTokenIds is a JSON array string)
            tokens = m.get("tokens", [])
            clob_ids_raw = m.get("clobTokenIds", "")
            clob_ids = []
            if isinstance(clob_ids_raw, str) and clob_ids_raw.startswith("["):
                try:
                    clob_ids = _json.loads(clob_ids_raw)
                except _json.JSONDecodeError:
                    clob_ids = []
            elif isinstance(clob_ids_raw, list):
                clob_ids = clob_ids_raw
            elif isinstance(clob_ids_raw, str) and clob_ids_raw:
                clob_ids = [t.strip() for t in clob_ids_raw.split(",") if t.strip()]

            yes_token = ""
            no_token = ""
            if len(tokens) >= 2:
                yes_token = tokens[0].get("token_id", "")
                no_token = tokens[1].get("token_id", "")
            elif len(clob_ids) >= 2:
                yes_token = clob_ids[0]
                no_token = clob_ids[1]

            if not yes_token:
                continue

            suitable.append(MarketInfo(
                condition_id=m.get("conditionId", m.get("condition_id", m.get("id", ""))),
                question=m.get("question", ""),
                yes_token_id=yes_token,
                no_token_id=no_token,
                end_date=end_date_str,
                volume=volume,
                volume_24h=volume_24h,
                liquidity=liquidity,
                category=category,
                active=active,
                closed=closed,
                resolution=m.get("resolution"),
            ))

        # Sort by liquidity descending
        suitable.sort(key=lambda x: x.liquidity, reverse=True)
        print(f"Found {len(suitable)} markets suitable for MM "
              f"(from {len(all_raw)} total)")
        return suitable

    def fetch_prices_history(
        self,
        token_id: str,
        interval: str = "1h",
        fidelity: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Fetch hourly price history from CLOB /prices-history.

        Args:
            token_id: Token contract address (CLOB asset ID)
            interval: Time interval (1m, 5m, 1h, 1d)
            fidelity: Data fidelity in minutes

        Returns:
            List of {t: timestamp, p: price} dicts
        """
        params = {
            "market": token_id,
            "interval": "max",
            "fidelity": 1,
        }

        try:
            resp = self.session.get(
                self.CLOB_PRICES_URL,
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            time.sleep(self.rate_limit_delay)
            data = resp.json()
            if isinstance(data, dict) and "history" in data:
                return data["history"]
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            print(f"  Error fetching prices for {token_id}: {e}")
            return []

    def collect_price_history(
        self,
        markets: List[MarketInfo],
        days: int = 90,
        snapshots_per_day: int = 4,
    ) -> List[HistoricalSnapshot]:
        """
        Collect price history for multiple markets.
        Uses CLOB /prices-history for hourly data, then downsamples.

        Args:
            markets: List of MarketInfo to collect for
            days: Days of history
            snapshots_per_day: Target snapshots per day in output

        Returns:
            List of HistoricalSnapshot ready for backtest engine
        """
        all_snapshots: List[HistoricalSnapshot] = []
        start_date = datetime.now() - timedelta(days=days)
        interval_hours = 24 // snapshots_per_day

        for idx, market in enumerate(markets):
            print(f"[{idx+1}/{len(markets)}] Collecting: {market.question[:60]}...")

            # Fetch hourly prices
            history = self.fetch_prices_history(
                market.yes_token_id,
                interval="1h",
                fidelity=60,
            )

            if not history:
                print(f"  No price history, trying trade-based method...")
                trades = self.fetch_trades(market.yes_token_id, limit=500)
                if trades:
                    price_pairs = self._build_price_history(
                        trades, start_date, snapshots_per_day
                    )
                    for ts, price in price_pairs:
                        all_snapshots.append(HistoricalSnapshot(
                            timestamp=ts.isoformat(),
                            market_id=market.condition_id,
                            question=market.question,
                            yes_price=round(price, 4),
                            no_price=round(1 - price, 4),
                            volume=market.volume,
                            volume_24h=market.volume_24h,
                            liquidity=market.liquidity,
                            end_date=market.end_date,
                            resolved=market.closed,
                            resolution=market.resolution,
                        ))
                continue

            # Parse and downsample price history
            prices_by_time = []
            for point in history:
                ts_raw = point.get("t", 0)
                price = float(point.get("p", 0.5))

                # Handle both epoch seconds and ISO strings
                if isinstance(ts_raw, (int, float)):
                    if ts_raw > 1e12:
                        ts_raw = ts_raw / 1000  # ms to seconds
                    ts = datetime.fromtimestamp(ts_raw)
                elif isinstance(ts_raw, str):
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
                else:
                    continue

                if ts >= start_date:
                    prices_by_time.append((ts, price))

            if not prices_by_time:
                print(f"  No data in date range")
                continue

            prices_by_time.sort(key=lambda x: x[0])

            # Downsample to target frequency
            current_slot = start_date
            price_idx = 0
            last_price = prices_by_time[0][1]

            while current_slot < datetime.now():
                # Find closest price at or before this slot
                while (price_idx < len(prices_by_time) - 1 and
                       prices_by_time[price_idx + 1][0] <= current_slot):
                    price_idx += 1

                if price_idx < len(prices_by_time):
                    if prices_by_time[price_idx][0] <= current_slot:
                        last_price = prices_by_time[price_idx][1]

                all_snapshots.append(HistoricalSnapshot(
                    timestamp=current_slot.isoformat(),
                    market_id=market.condition_id,
                    question=market.question,
                    yes_price=round(last_price, 4),
                    no_price=round(1 - last_price, 4),
                    volume=market.volume,
                    volume_24h=market.volume_24h,
                    liquidity=market.liquidity,
                    end_date=market.end_date,
                    resolved=market.closed,
                    resolution=market.resolution,
                ))

                current_slot += timedelta(hours=interval_hours)

            print(f"  Collected {sum(1 for s in all_snapshots if s.market_id == market.condition_id)} snapshots")

        all_snapshots.sort(key=lambda x: x.timestamp)
        print(f"\nTotal: {len(all_snapshots)} snapshots across {len(markets)} markets")
        return all_snapshots

    def load_archive_orderbook(
        self,
        date_str: str,
        market_slug: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Load orderbook snapshot from archive.pmxt.dev (Parquet format).

        Archive structure: archive.pmxt.dev/Polymarket/{YYYY-MM-DD}/orderbook.parquet

        Args:
            date_str: Date string "YYYY-MM-DD"
            market_slug: Optional market slug to filter

        Returns:
            DataFrame with orderbook data, or None
        """
        url = f"{self.ARCHIVE_BASE_URL}/{date_str}/orderbook.parquet"

        cache_key = f"archive_ob_{date_str}"
        cached = self.load_cache(cache_key, max_age_hours=168)  # 1 week cache
        if cached is not None:
            df = pd.DataFrame(cached)
            if market_slug:
                df = df[df["market_slug"].str.contains(market_slug, na=False)]
            return df

        try:
            print(f"  Downloading orderbook for {date_str}...")
            df = pd.read_parquet(url)

            # Cache the data
            self.cache_data(cache_key, df.to_dict(orient="records"))

            if market_slug:
                df = df[df["market_slug"].str.contains(market_slug, na=False)]
            return df
        except Exception as e:
            print(f"  Error loading archive for {date_str}: {e}")
            return None

    def collect_archive_snapshots(
        self,
        markets: List[MarketInfo],
        start_date: str,
        end_date: str,
    ) -> List[HistoricalSnapshot]:
        """
        Collect orderbook-based snapshots from archive.pmxt.dev.
        Provides richer data (bid/ask spread, depth) than CLOB price history.

        Args:
            markets: Markets to collect
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"

        Returns:
            List of HistoricalSnapshot
        """
        snapshots = []
        market_ids = {m.condition_id for m in markets}
        market_lookup = {m.condition_id: m for m in markets}

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        current = start

        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            df = self.load_archive_orderbook(date_str)

            if df is not None and len(df) > 0:
                # Filter for our markets
                if "condition_id" in df.columns:
                    df_filtered = df[df["condition_id"].isin(market_ids)]
                elif "market_id" in df.columns:
                    df_filtered = df[df["market_id"].isin(market_ids)]
                else:
                    df_filtered = df

                for _, row in df_filtered.iterrows():
                    mid = row.get("condition_id", row.get("market_id", ""))
                    market = market_lookup.get(mid)
                    if not market:
                        continue

                    # Extract best bid/ask if available
                    best_bid = float(row.get("best_bid", 0))
                    best_ask = float(row.get("best_ask", 0))
                    mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.5

                    ts = row.get("timestamp", current.isoformat())
                    if isinstance(ts, (int, float)):
                        ts = datetime.fromtimestamp(ts).isoformat()

                    snapshots.append(HistoricalSnapshot(
                        timestamp=str(ts),
                        market_id=mid,
                        question=market.question,
                        yes_price=round(mid_price, 4),
                        no_price=round(1 - mid_price, 4),
                        volume=market.volume,
                        volume_24h=market.volume_24h,
                        liquidity=float(row.get("liquidity", market.liquidity)),
                        end_date=market.end_date,
                        resolved=market.closed,
                        resolution=market.resolution,
                    ))

                print(f"  {date_str}: {len(df_filtered)} orderbook entries")

            current += timedelta(days=1)

        snapshots.sort(key=lambda x: x.timestamp)
        return snapshots


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Collect market-making data from Polymarket"
    )
    parser.add_argument("--output", default="data/mm_historical.json")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--min-volume", type=float, default=10_000)
    parser.add_argument("--min-liquidity", type=float, default=5_000)
    parser.add_argument("--max-markets", type=int, default=50)
    parser.add_argument("--cache-dir", default="data/cache")

    args = parser.parse_args()

    collector = MMDataCollector(cache_dir=args.cache_dir)

    print("Finding suitable markets...")
    markets = collector.find_mm_markets(
        min_volume_24h=args.min_volume,
        min_liquidity=args.min_liquidity,
        max_markets=args.max_markets,
    )

    if not markets:
        print("No suitable markets found.")
        exit(1)

    print(f"\nTop 5 markets by liquidity:")
    for m in markets[:5]:
        print(f"  ${m.liquidity:>10,.0f} | {m.question[:60]}")

    print(f"\nCollecting {args.days} days of price history...")
    snapshots = collector.collect_price_history(markets, days=args.days)

    if snapshots:
        collector.save_snapshots(snapshots, args.output)
        print(f"\nSaved {len(snapshots)} snapshots to {args.output}")
    else:
        print("No snapshots collected.")
