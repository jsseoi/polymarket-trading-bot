# Academic Research Summary

A curated collection of academic research relevant to prediction market trading strategies.

## Key Papers

### 1. Systematic Edges in Prediction Markets (QuantPedia, 2025)

**Source**: [quantpedia.com](https://quantpedia.com/systematic-edges-in-prediction-markets/)

**Key Findings**:
- Prediction markets have systematic inefficiencies that create trading opportunities
- Inter- and intra-market arbitrage opportunities exist and are exploitable
- Longshot bias leads traders to overvalue underdogs and undervalue favorites
- Experienced traders can exploit these patterns for consistent profits

**Relevant Strategies**:
- Intra-market arbitrage (buy-all/sell-all when prices don't sum to 1)
- Cross-platform arbitrage (price discrepancies across Polymarket, Kalshi, PredictIt)
- Longshot bias exploitation

---

### 2. Price Discovery and Trading in Prediction Markets (SSRN, 2025)

**Source**: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5331995)

**Key Findings**:
- Polymarket generally leads Kalshi in price discovery due to higher liquidity
- Arbitrage opportunities typically exist for only seconds to minutes
- Transaction costs significantly reduce potential profits
- Last hours before market closing show highest price efficiency

**Practical Implications**:
- Speed is critical for arbitrage strategies
- Polymarket is the primary price setter for US political events
- Focus on less liquid markets for larger spreads

---

### 3. Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets (arXiv, 2025)

**Source**: [arXiv](https://arxiv.org/abs/2508.03474)

**Key Findings**:
- Examines both political and sports prediction markets on Polymarket
- Identifies arbitrage opportunities in logically connected markets
- Lower liquidity and profits compared to cross-platform arbitrage
- Opportunities arise from inconsistent pricing in related markets

**Example**:
If "Candidate X wins nationally" is 60% but "Candidate X wins Pennsylvania" is only 40%, this represents a logical inconsistency that can be exploited.

---

### 4. Arbitrage in Political Prediction Markets (JPM, 2020)

**Source**: [Journal of Prediction Markets](https://www.ubplj.org/index.php/jpm/article/view/1796)

**Key Findings**:
- PredictIt showed significant arbitrage opportunities in 2014-2015
- Sum of contract prices often exceeded $1.00 (sell-all arbitrage)
- Opportunities of up to 55% profit per contract were found
- Introduction of linked markets and fees reduced but didn't eliminate arbitrage
- 2020 election showed lower arbitrage profits than 2016

**Historical Context**:
- Early prediction markets were highly inefficient
- Markets have become more efficient over time but opportunities persist

---

### 5. Biases in the Football Betting Market (SSRN, 2017)

**Source**: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2977118)

**Key Findings**:
- Analyzed 12,084 sports matches (Feb-May 2017)
- Betting on favorites: average loss of -3.64%
- Betting on longshots: average loss of -26.08%
- Clear evidence of longshot bias across sports betting

**Application to Prediction Markets**:
- Same psychological biases affect prediction market participants
- Systematic betting on favorites outperforms random betting
- Edge is consistent across different event types

---

### 6. The Favorite-Longshot Midas (SSRN, 2020)

**Source**: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3271248)

**Key Findings**:
- Bookmakers deliberately manipulate morning-line odds
- Naive traders are misled into thinking underdogs have higher win probability
- Skilled traders can identify "real" favorites vs. bookmaker manipulation
- Strategy: identify when bookmakers are creating false longshots

---

### 7. Price Biases in a Prediction Market: NFL Contracts on Tradesports (2007)

**Source**: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2149609)

**Key Findings**:
- Contracts priced below $20 significantly underperform expected returns
- Contracts above $80 show slight positive bias
- Confirms longshot bias in prediction market context
- Effect persists even in liquid markets

---

## Synthesis: Proven Strategies

Based on the academic research, these strategies have empirical support:

### Tier 1: Strong Evidence
| Strategy | Evidence Level | Expected Edge |
|----------|----------------|---------------|
| Longshot Bias | Multiple studies, 10+ years data | 8-15% annual |
| Intra-Market Arbitrage | Multiple studies | 2-5% per trade |
| Cross-Platform Arbitrage | Recent studies (2024-2025) | 3-7% per trade |

### Tier 2: Moderate Evidence
| Strategy | Evidence Level | Expected Edge |
|----------|----------------|---------------|
| News Velocity | Limited academic study | 5-15% annual |
| Sentiment Divergence | Emerging research | Unknown |

### Tier 3: Theoretical/Limited Evidence
| Strategy | Evidence Level | Expected Edge |
|----------|----------------|---------------|
| Market Making | Limited data | Varies widely |
| Machine Learning Prediction | Early stage | Unknown |

---

## Market Efficiency Timeline

Research shows prediction markets have become more efficient over time:

| Period | Efficiency Level | Arbitrage Opportunities |
|--------|------------------|-------------------------|
| 2014-2015 | Low | Frequent, large (up to 55%) |
| 2016-2019 | Medium | Moderate (5-15%) |
| 2020-2023 | Medium-High | Less frequent (3-8%) |
| 2024-2025 | Higher | Brief windows (2-5%) |

**Implications**:
- Opportunities still exist but require faster execution
- Spreads are narrower, requiring lower costs to profit
- Sophistication of traders has increased
- New markets (sports, crypto) may have more inefficiencies

---

## Research Gaps

Areas with limited academic study:

1. **Machine learning applications** to prediction markets
2. **Sentiment analysis** integration with market prices
3. **High-frequency trading** dynamics on Polymarket
4. **Sports vs. political** market efficiency comparison
5. **Impact of crypto-native platforms** on arbitrage dynamics

---

## Recommended Reading

### Books
- *Prediction Markets* by Leighton Vaughan Williams
- *Thinking, Fast and Slow* by Daniel Kahneman (behavioral biases)
- *The Wisdom of Crowds* by James Surowiecki

### Journals
- Journal of Prediction Markets
- Journal of Behavioral Finance
- Review of Financial Studies

### Platforms for Research
- SSRN (Social Science Research Network)
- arXiv (quantitative finance section)
- QuantPedia
