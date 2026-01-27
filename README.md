# Polymarket Trading Bot

A comprehensive research and trading framework for Polymarket prediction markets.

## 🎯 Overview

This repository contains:
- **4 Trading Strategies** - Based on academic research
- **Backtesting Engine** - Test strategies on historical data
- **Paper Trading** - Simulate trades without real money
- **CLI Tools** - Market analysis and scanning
- **API Clients** - Full Polymarket API integration

## 📊 Strategies

| Strategy | Expected Edge | Win Rate | Description |
|----------|---------------|----------|-------------|
| Longshot Bias | 2-3% | 58-62% | Bet on favorites, avoid longshots |
| Arbitrage | 2-5% | ~95% | Exploit pricing inefficiencies |
| Momentum | 3-5% | 55-60% | Trade on news velocity |
| Mean Reversion | 1-2% | 55-58% | Bet on price returning to mean |

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/clawdvandamme/polymarket-trading-bot.git
cd polymarket-trading-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### CLI Usage

```bash
# List top markets
python -m src.cli markets

# Scan for opportunities
python -m src.cli scan

# Run a backtest
python -m src.cli backtest -s longshot --days 90

# Compare all strategies
python -m src.cli compare

# Analyze a specific market
python -m src.cli analyze "Trump"
```

### Paper Trading

```bash
# Check portfolio status
python -m src.paper_trading status

# Buy YES on a market
python -m src.paper_trading buy "Trump" --amount 100

# Buy NO (sell YES)
python -m src.paper_trading sell "Biden" --amount 100

# Close a position
python -m src.paper_trading close <position_id>

# Reset portfolio
python -m src.paper_trading reset --cash 10000
```

## 📁 Project Structure

```
polymarket-trading-bot/
├── src/
│   ├── api/
│   │   ├── gamma_client.py    # Market discovery API
│   │   └── clob_client.py     # Order book API
│   ├── strategies/
│   │   ├── base_strategy.py   # Abstract strategy class
│   │   ├── longshot_bias.py   # Favorite betting
│   │   ├── arbitrage.py       # Dutch book detection
│   │   ├── momentum.py        # News velocity
│   │   └── mean_reversion.py  # Bollinger bands
│   ├── backtesting/
│   │   └── engine.py          # Backtest simulation
│   ├── data/
│   │   └── fetcher.py         # Historical data
│   ├── cli.py                 # Command-line interface
│   └── paper_trading.py       # Paper trading simulator
├── docs/
│   ├── API_REFERENCE.md       # API documentation
│   ├── STRATEGIES.md          # Strategy deep dive
│   ├── RESEARCH.md            # Academic research
│   └── ACADEMIC_RESEARCH.md   # Key papers summary
├── notebooks/
│   └── strategy_analysis.py   # Analysis script
└── requirements.txt
```

## 📈 Backtesting

The backtesting engine supports:
- Synthetic data generation
- Real historical data (JSON format)
- Commission and slippage modeling
- Equity curve tracking
- Performance metrics (Sharpe, drawdown, etc.)

```python
from src.backtesting.engine import BacktestEngine, BacktestConfig
from src.strategies.longshot_bias import LongshotBiasStrategy

engine = BacktestEngine()
engine.generate_synthetic_data(num_markets=50, days=90)

strategy = LongshotBiasStrategy()
config = BacktestConfig(
    start_date=datetime.now() - timedelta(days=90),
    end_date=datetime.now(),
    initial_capital=10000
)

result = engine.run(strategy, config)
print(result.summary())
```

## 🔬 Research

The strategies are based on academic research:

- **Snowberg & Wolfers (2010)** - Favorite-longshot bias
- **Thaler & Ziemba (1988)** - Market efficiency
- **Vaughan Williams (1999)** - Information efficiency

See `docs/ACADEMIC_RESEARCH.md` for full paper summaries.

## ⚠️ Disclaimer

This is for educational and research purposes only. Trading prediction markets involves risk. Past performance does not guarantee future results. Never trade with money you can't afford to lose.

## 📜 License

MIT

---

*Built with 🔥 by Clawd*
