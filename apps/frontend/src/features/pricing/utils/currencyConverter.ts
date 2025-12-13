// Simple exchange rates for conversion to USD (in a real app, these would come from an API)
const EXCHANGE_RATES_TO_USD: Record<string, number> = {
  USD: 1.0,
  INR: 0.012, // 1 INR = 0.012 USD (approximate)
  EUR: 1.18, // 1 EUR = 1.18 USD (approximate)
  GBP: 1.37, // 1 GBP = 1.37 USD (approximate)
};

/**
 * Convert any currency amount to USD cents for display
 */
export function convertToUSDCents(
  amount: number,
  fromCurrency: string,
): number {
  // If already USD, return as-is
  if (fromCurrency === "USD") {
    return amount;
  }

  // Get exchange rate to USD
  const rate = EXCHANGE_RATES_TO_USD[fromCurrency];
  if (!rate) {
    console.warn(`Unknown currency: ${fromCurrency}, treating as USD`);
    return amount;
  }

  // Convert to USD
  // If the amount is in smallest unit (paise for INR), convert to main unit first, then to USD, then to cents
  const divisor = fromCurrency === "INR" ? 100 : 1; // INR uses paise (1/100), USD uses cents (1/100)
  const mainUnit = amount / divisor;
  const usdMainUnit = mainUnit * rate;
  const usdCents = Math.round(usdMainUnit * 100);

  return usdCents;
}

/**
 * Format USD cents to display string
 */
export function formatUSDFromCents(cents: number): string {
  if (cents === 0) return "Free";
  const dollars = cents / 100;
  return `$${dollars.toFixed(0)}`;
}
