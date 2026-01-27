# Polymarket API Reference

Complete documentation for programmatic access to Polymarket prediction markets.

## Overview

Polymarket provides three main APIs:

| API | Base URL | Purpose |
|-----|----------|---------|
| CLOB API | `https://clob.polymarket.com` | Order management, prices, orderbook |
| Gamma API | `https://gamma-api.polymarket.com` | Market discovery, metadata, events |
| Data API | `https://data-api.polymarket.com` | User positions, activity, history |

### WebSocket Endpoints

| Service | URL | Purpose |
|---------|-----|---------|
| CLOB WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/` | Orderbook updates, order status |
| RTDS | `wss://ws-live-data.polymarket.com` | Low-latency prices, comments |

---

## Authentication

Polymarket uses two levels of authentication:

### L1 Authentication (Private Key)

L1 uses the wallet's private key to sign an EIP-712 message. Required for:
- Creating API credentials
- Deriving existing API credentials
- Signing orders locally

**Headers Required:**
```
POLY_ADDRESS: <Polygon signer address>
POLY_SIGNATURE: <EIP-712 signature>
POLY_TIMESTAMP: <Current UNIX timestamp>
POLY_NONCE: <Nonce, default 0>
```

**Create/Derive API Credentials:**
```python
from py_clob_client.client import ClobClient
import os

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,  # Polygon mainnet
    key=os.getenv("PRIVATE_KEY")
)

# Gets API key, or creates if doesn't exist
api_creds = client.create_or_derive_api_key()
# Returns: {apiKey, secret, passphrase}
```

### L2 Authentication (API Key)

L2 uses HMAC-SHA256 signatures with API credentials. Required for:
- Posting signed orders
- Canceling orders
- Viewing open orders
- Checking balances

**Headers Required:**
```
POLY_ADDRESS: <Polygon signer address>
POLY_SIGNATURE: <HMAC signature>
POLY_TIMESTAMP: <Current UNIX timestamp>
POLY_API_KEY: <API key>
POLY_PASSPHRASE: <Passphrase>
```

**Signature Types:**

| Type | Value | Description |
|------|-------|-------------|
| EOA | 0 | Standard Ethereum wallet |
| POLY_PROXY | 1 | Magic Link/Google login proxy wallet |
| GNOSIS_SAFE | 2 | Gnosis Safe multisig (most common) |

---

## CLOB API Endpoints

### Public Endpoints (No Auth Required)

#### Get Price
```http
GET /price?token_id={token_id}&side={BUY|SELL}
```

**Response:**
```json
{
  "price": "0.65"
}
```

#### Get Orderbook
```http
GET /book?token_id={token_id}
```

**Response:**
```json
{
  "market": "0x123...",
  "asset_id": "token_id",
  "bids": [
    {"price": "0.64", "size": "1000"},
    {"price": "0.63", "size": "500"}
  ],
  "asks": [
    {"price": "0.66", "size": "800"},
    {"price": "0.67", "size": "1200"}
  ]
}
```

#### Get Midpoint
```http
GET /midpoint?token_id={token_id}
```

**Response:**
```json
{
  "mid": "0.65"
}
```

#### Get Markets
```http
GET /markets?next_cursor={cursor}
```

#### Get Market
```http
GET /markets/{condition_id}
```

### Authenticated Endpoints (L2 Required)

#### Place Order
```http
POST /order
Content-Type: application/json

{
  "order": {
    "tokenID": "123456",
    "price": "0.65",
    "size": "100",
    "side": "BUY",
    "feeRateBps": "0",
    "nonce": "123",
    "expiration": "0",
    "signatureType": 2,
    "signature": "0x..."
  }
}
```

#### Cancel Order
```http
DELETE /order/{order_id}
```

#### Cancel All Orders
```http
DELETE /orders
```

#### Get Open Orders
```http
GET /orders?market={market_id}
```

---

## Gamma API Endpoints

The Gamma API provides market discovery and metadata.

### Get Events
```http
GET /events?limit=100&offset=0&active=true
```

**Response:**
```json
{
  "data": [
    {
      "id": "event-uuid",
      "title": "2024 US Presidential Election",
      "slug": "2024-us-presidential-election",
      "description": "...",
      "startDate": "2024-11-05T00:00:00Z",
      "endDate": "2024-11-06T00:00:00Z",
      "markets": [
        {
          "id": "market-uuid",
          "question": "Will Trump win?",
          "conditionId": "0x...",
          "slug": "trump-wins"
        }
      ]
    }
  ]
}
```

### Get Markets
```http
GET /markets?limit=100&active=true&closed=false
```

### Get Single Event
```http
GET /events/{event_id}
```

### Get Single Market
```http
GET /markets/{market_id}
```

### Search
```http
GET /markets/search?query=trump
```

---

## Data API Endpoints

### Get Positions
```http
GET /positions?user={address}
```

### Get Activity
```http
GET /activity?user={address}
```

### Get Trade History
```http
GET /trades?user={address}&market={market_id}
```

---

## WebSocket API

### Connection
```javascript
const ws = new WebSocket('wss://ws-subscriptions-clob.polymarket.com/ws/');
```

### Subscribe to Market Channel (Public)
```json
{
  "type": "subscribe",
  "channel": "market",
  "assets_ids": ["token_id_1", "token_id_2"]
}
```

### Subscribe to User Channel (Authenticated)
```json
{
  "type": "subscribe", 
  "channel": "user",
  "auth": {
    "apiKey": "...",
    "secret": "...",
    "passphrase": "..."
  }
}
```

### Market Update Messages
```json
{
  "type": "book",
  "asset_id": "token_id",
  "market": "market_id",
  "bids": [...],
  "asks": [...]
}
```

### Price Update Messages
```json
{
  "type": "price_change",
  "asset_id": "token_id",
  "price": "0.67",
  "timestamp": 1234567890
}
```

---

## Python Client Examples

### Installation
```bash
pip install py-clob-client
```

### Basic Usage
```python
from py_clob_client.client import ClobClient
import os

# Initialize client
client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key=os.getenv("PRIVATE_KEY"),
    creds={
        "apiKey": os.getenv("API_KEY"),
        "secret": os.getenv("API_SECRET"),
        "passphrase": os.getenv("API_PASSPHRASE")
    },
    signature_type=2  # GNOSIS_SAFE
)

# Get markets
markets = client.get_markets()

# Get orderbook
book = client.get_order_book(token_id="123456")

# Place order (authenticated)
order = client.create_and_post_order(
    {"tokenID": "123456", "price": 0.65, "size": 100, "side": "BUY"},
    {"tickSize": "0.01", "negRisk": False}
)

# Cancel order
client.cancel(order_id="order-uuid")
```

### Fetch All Markets with Metadata
```python
import requests

def get_all_markets():
    """Fetch all active markets from Gamma API"""
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 100
    }
    
    markets = []
    offset = 0
    
    while True:
        params["offset"] = offset
        response = requests.get(url, params=params)
        data = response.json()
        
        if not data:
            break
            
        markets.extend(data)
        offset += len(data)
        
        if len(data) < 100:
            break
    
    return markets
```

---

## Rate Limits

- Public endpoints: 100 requests/minute
- Authenticated endpoints: 300 requests/minute
- WebSocket: 10 subscriptions per connection

## Fees

Current fee schedule (subject to change):

| Volume Level | Maker Fee | Taker Fee |
|--------------|-----------|-----------|
| > 0 USDC | 0 bps | 0 bps |

**Winner Fee**: 2% on winning positions at settlement.

Fee calculation:
- Selling tokens: `fee = baseRate × min(price, 1-price) × size`
- Buying tokens: `fee = baseRate × min(price, 1-price) × size/price`

---

## Resources

- [Official Documentation](https://docs.polymarket.com/)
- [TypeScript Client](https://github.com/Polymarket/clob-client)
- [Python Client](https://github.com/Polymarket/py-clob-client)
- [Exchange Contract Audit](https://github.com/Polymarket/ctf-exchange/blob/main/audit/ChainSecurity_Polymarket_Exchange_audit.pdf)
