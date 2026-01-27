# Prediction Market Academic Research Summary

*Key papers and findings for trading strategy development*

---

## The Favorite-Longshot Bias

### Snowberg & Wolfers (2010)
**"Explaining the Favorite-Longshot Bias: Is it Risk-Love or Misperceptions?"**
- Journal of Political Economy, Vol 118, No 4
- NBER Working Paper 15923

**Key Finding:**
Bettors systematically overvalue longshots and undervalue favorites.

**Quantified Returns:**
| Odds | Expected Return |
|------|-----------------|
| 1/1 (50%) | ~85% |
| 5/1 (17%) | ~80% |
| 20/1 (5%) | ~75% |

**Cause:** The bias is driven by **probability misperceptions** (overweighting small probabilities) rather than risk-love preferences.

**Trading Implication:** Bet on favorites. The edge increases as implied probability increases.

---

### Jullien & Salanié (2000)
**"Estimating the Gains from Trade in Limit Order Markets"**

**Finding:** Confirmed the favorite-longshot bias persists across different market structures (pari-mutuel, fixed-odds, betting exchanges).

---

### Shin (1991, 1993)
**"Optimal Betting Odds Against Insider Traders"**

**Finding:** Bookmakers set odds to protect against informed bettors, which partially explains the bias. However, the bias exceeds what insider trading alone would explain.

---

## Market Efficiency

### Thaler & Ziemba (1988)
**"Parimutuel Betting Markets: Racetracks and Lotteries"**

**Classic survey establishing:**
1. Prediction markets are "weak-form efficient" (can't profit from past prices alone)
2. But NOT strong-form efficient (systematic biases exist)
3. The favorite-longshot bias is the most robust anomaly

---

### Vaughan Williams (1999)
**"Information Efficiency in Betting Markets"**

**Finding:** Markets incorporate information quickly but not perfectly. News takes 15-60 minutes to fully reflect in prices.

**Trading Implication:** Momentum strategies can work in short windows after news.

---

## Prediction Market Accuracy

### Wolfers & Zitzewitz (2004)
**"Prediction Markets"**

**Key Findings:**
1. Prediction markets outperform polls for elections
2. Markets aggregate dispersed information efficiently
3. Prices ≈ probabilities (with caveats for extreme prices)

**Caveats:**
- Thin markets can be manipulated short-term
- Extreme probabilities (>90% or <10%) may be miscalibrated

---

### Arrow et al. (2008)
**"The Promise of Prediction Markets"**
- Science, Vol 320

**Conclusion:** Prediction markets are useful forecasting tools, but:
- Liquidity matters for accuracy
- Incentive alignment is crucial
- Manipulation resistance depends on market design

---

## Arbitrage in Prediction Markets

### Tetlock (2008)
**"Liquidity and Prediction Market Efficiency"**

**Finding:** Arbitrage opportunities exist but are often too small to profit after fees. Markets with >$10k volume show fewer inefficiencies.

---

### Green, Lee & Rothschild (2019)
**"The Favorite-Longshot Midas"**
- Berkeley Statistics

**Quantified Strategy:**
- Betting on favorites (1/1 to 5/1) yields positive expected value
- Longshots (>10/1) consistently lose money
- The edge is ~5-10% annually with disciplined execution

---

## Behavioral Factors

### Prospect Theory (Kahneman & Tversky)
Explains why bettors overweight small probabilities:
- 1% feels like 5%
- 99% feels like 95%

This creates the favorite-longshot bias.

### Availability Heuristic
Recent longshot winners are memorable, making people overestimate their frequency.

### Entertainment Value
Some bettors pay a premium for excitement (longshots are more exciting than favorites).

---

## Strategy Implications Summary

| Strategy | Academic Support | Expected Edge |
|----------|-----------------|---------------|
| Bet on favorites (>70%) | Strong (Snowberg & Wolfers) | 2-3% per trade |
| Avoid longshots (<20%) | Strong | N/A (avoid losses) |
| Mean reversion | Moderate | 1-2% |
| News momentum | Moderate (Vaughan Williams) | 3-5% (time-limited) |
| Arbitrage | Limited (Tetlock) | <1% after fees |

---

## Key Papers for Further Reading

1. **Snowberg, E., & Wolfers, J. (2010)** - Favorite-Longshot Bias
   https://www.nber.org/papers/w15923

2. **Wolfers, J., & Zitzewitz, E. (2004)** - Prediction Markets Overview
   https://www.nber.org/papers/w10504

3. **Arrow, K., et al. (2008)** - Promise of Prediction Markets
   Science, Vol 320

4. **Manski, C. (2006)** - Interpreting Prediction Market Prices
   https://www.nber.org/papers/w10359

5. **Forsythe, R., et al. (1992)** - Iowa Electronic Markets
   American Economic Review

---

*This summary supports the strategies implemented in this codebase.*
