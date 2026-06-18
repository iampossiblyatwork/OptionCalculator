// Black–Scholes twin of options.py:black_scholes — keep formulas in sync.
// Conventions: theta per calendar day; vega & rho per 1% move; rates/vol as decimals.
(function (root) {
  const DAYS_PER_YEAR = 365;

  // Abramowitz & Stegun 7.1.26 — max abs error ~1.5e-7, ample for parity.
  function erf(x) {
    const sign = x < 0 ? -1 : 1;
    x = Math.abs(x);
    const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
    const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
    const t = 1 / (1 + p * x);
    const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
    return sign * y;
  }

  function normCdf(x) { return 0.5 * (1 + erf(x / Math.SQRT2)); }
  function normPdf(x) { return 0.3989422804014327 * Math.exp(-x * x / 2); }
  function intrinsic(type, strike, price) {
    return type === "call" ? Math.max(price - strike, 0) : Math.max(strike - price, 0);
  }

  function blackScholes({ type, spot, strike, daysToExpiration, volatility,
                          riskFreeRate = 0.04, dividendYield = 0 }) {
    const r = riskFreeRate, q = dividendYield, S = spot, K = strike;
    const T = daysToExpiration / DAYS_PER_YEAR, sigma = volatility;

    if (T <= 0 || sigma <= 0 || S <= 0 || K <= 0) {
      const price = intrinsic(type, K, S);
      const itm = type === "call" ? S > K : S < K;
      return {
        price, delta: itm ? (type === "call" ? 1 : -1) : 0,
        gamma: 0, theta: 0, vega: 0, rho: 0,
        d1: 0, d2: 0, nD1: 0, nD2: 0,
        probItm: itm ? 1 : 0, moneyness: K > 0 ? S / K : 0,
      };
    }

    const sqrtT = Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r - q + sigma * sigma / 2) * T) / (sigma * sqrtT);
    const d2 = d1 - sigma * sqrtT;
    const discR = Math.exp(-r * T), discQ = Math.exp(-q * T);

    let price, delta, rho, theta;
    if (type === "call") {
      price = S * discQ * normCdf(d1) - K * discR * normCdf(d2);
      delta = discQ * normCdf(d1);
      rho = K * T * discR * normCdf(d2) / 100;
      theta = (-(S * discQ * normPdf(d1) * sigma) / (2 * sqrtT)
               - r * K * discR * normCdf(d2)
               + q * S * discQ * normCdf(d1)) / DAYS_PER_YEAR;
    } else {
      price = K * discR * normCdf(-d2) - S * discQ * normCdf(-d1);
      delta = discQ * (normCdf(d1) - 1);
      rho = -K * T * discR * normCdf(-d2) / 100;
      theta = (-(S * discQ * normPdf(d1) * sigma) / (2 * sqrtT)
               + r * K * discR * normCdf(-d2)
               - q * S * discQ * normCdf(-d1)) / DAYS_PER_YEAR;
    }
    const gamma = discQ * normPdf(d1) / (S * sigma * sqrtT);
    const vega = S * discQ * normPdf(d1) * sqrtT / 100;
    const probItm = type === "call" ? normCdf(d2) : normCdf(-d2);

    return { price, delta, gamma, theta, vega, rho, d1, d2,
             nD1: normCdf(d1), nD2: normCdf(d2), probItm, moneyness: S / K };
  }

  const api = { blackScholes, normCdf, erf };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else { root.BS = api; }
})(typeof window !== "undefined" ? window : globalThis);
