# TaoQuant Grid Trading Bot

Clean, focused grid trading bot for cryptocurrency markets using Bitget exchange.

## Features

- **StandardGridV2**: Exchange-compliant grid trading with 1 order per grid level
- **ATR-based Spacing**: Dynamic grid spacing calculated from market volatility
- **Bitget Integration**: Uses CCXT library for reliable exchange connectivity
- **Dry Run Mode**: Test strategies without risking real capital
- **Simple Deployment**: Minimal dependencies, easy to deploy

## Quick Start

### 1. Installation

```bash
# Clone repository
git clone <your-repo-url>
cd taoquant-grid

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your Bitget API credentials
# Get API keys from: https://www.bitget.com/api/
```

### 3. Run

```bash
# Dry run (paper trading)
python run_live.py --balance 100 --leverage 10 --dry-run

# Live trading
python run_live.py --balance 100 --leverage 10
```

## Command Line Options

```bash
python run_live.py [OPTIONS]

Options:
  --support FLOAT       Support level (default: 76000)
  --resistance FLOAT    Resistance level (default: 97000)
  --balance FLOAT       Initial balance in USDT (default: 100)
  --leverage FLOAT      Leverage multiplier (default: 10)
  --symbol TEXT         Trading symbol (default: BTCUSDT)
  --dry-run            Enable dry run mode (paper trading)
```

## How It Works

### Grid Trading Logic

1. **Initialize Grid**: Place buy orders at grid levels below current price
2. **Buy Fill**: When buy@grid[i] fills → place sell@grid[i+1]
3. **Sell Fill**: When sell@grid[i] fills → re-place buy@grid[i]
4. **Continuous Loop**: Repeat buy-low, sell-high cycle

### ATR-based Spacing

Grid spacing is dynamically calculated based on:
- Average True Range (ATR) for market volatility
- Minimum return requirement (0.5%)
- Trading fees (0.02% maker fee)
- Volatility multiplier (configurable)

Formula:
```
spacing = min_return + 2 * maker_fee + volatility_k * ATR%
grid_count = log(upper/lower) / log(1 + spacing)
```

## Architecture

```
taoquant-grid/
├── grid/                 # Core grid trading logic
│   ├── core.py          # StandardGridV2 implementation
│   └── config.py        # GridConfig dataclass
├── exchange/            # Exchange integration
│   └── bitget.py        # BitgetClient using CCXT
├── utils/               # Utilities
│   └── indicators.py    # ATR and grid calculations
└── run_live.py          # Main entry point
```

## Safety Features

- **Position Limits**: Maximum position size limits
- **Drawdown Control**: Maximum drawdown protection
- **Order Cleanup**: Automatic order cancellation on shutdown
- **Dry Run Mode**: Test without real money

## Example Output

```
================================================================================
TaoQuant Grid Trader - LIVE TRADING
================================================================================
Symbol: BTCUSDT
Range: $76,000 - $97,000
Balance: $100.00
Leverage: 10X
================================================================================

Initializing grid...
Loaded 500 bars
Average spacing: 0.0125 (1.25%)
Auto-calculated grid count: 15

Grid initialized:
  Active buy orders: 8
  Total grids: 15

[BUY FILL] Grid 5 @ $82,450.00, size=0.012134 BTC, fee=$2.00
  -> Placed SELL at grid 6 @ $83,481.25

[SELL FILL] Grid 6 @ $83,481.25, size=0.012134 BTC, PnL=$10.52 (+1.25%)
  -> Re-placed BUY at grid 5 @ $82,450.00
```

## Configuration

Edit `grid/config.py` to customize:

```python
@dataclass
class GridConfig:
    support: float              # Lower price bound
    resistance: float           # Upper price bound
    initial_cash: float         # Starting capital
    leverage: float             # Leverage (1-100)
    mode: str                   # "geometric" or "arithmetic"

    # ATR spacing
    min_return: float = 0.005   # 0.5% minimum return
    maker_fee: float = 0.0002   # 0.02% maker fee
    volatility_k: float = 0.6   # Volatility multiplier
    atr_period: int = 14        # ATR period

    # Safety limits
    max_position_usd: float = 10000.0
    max_drawdown_pct: float = 0.20
```

## License

MIT

## Disclaimer

This software is for educational purposes only. Trading cryptocurrencies carries substantial risk. Use at your own risk.
