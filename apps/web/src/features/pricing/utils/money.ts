/**
 * One reading of an API amount: minor units in the currency they were charged
 * in, divided by that currency's own exponent (2 for USD, 0 for JPY, 3 for KWD).
 */

/** ISO 4217's exponent for any code Intl cannot resolve. */
const ISO_4217_DEFAULT_EXPONENT = 2;

/** Intl throws only for a code that is not three ASCII letters; a well-formed
 *  but unknown code renders as the code itself. */
const WELL_FORMED_CURRENCY = /^[A-Za-z]{3}$/;

/** One formatter per currency, built once: constructing an
 *  `Intl.NumberFormat` is the expensive part, and prices re-render. */
const MONEY_FORMATTERS = new Map<string, Intl.NumberFormat>();

function moneyFormatter(code: string): Intl.NumberFormat {
  const cached = MONEY_FORMATTERS.get(code);
  if (cached) return cached;
  const formatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: code,
    currencyDisplay: "narrowSymbol",
  });
  MONEY_FORMATTERS.set(code, formatter);
  return formatter;
}

export function isWellFormedCurrency(code: string): boolean {
  return WELL_FORMED_CURRENCY.test(code);
}

/** Digits after the decimal point in the currency's major unit. */
export function currencyExponent(code: string): number {
  if (!isWellFormedCurrency(code)) return ISO_4217_DEFAULT_EXPONENT;
  return moneyFormatter(code).resolvedOptions().maximumFractionDigits ?? 0;
}

/** A minor-unit amount in the currency's major unit (3000 USD cents -> 30). */
export function toMajorUnits(amountMinor: number, currency: string): number {
  return amountMinor / 10 ** currencyExponent(currency);
}

/** A minor-unit amount with its own currency's symbol: 2584 EUR -> "€25.84". */
export function formatMoney(amountMinor: number, currency: string): string {
  return moneyFormatter(currency).format(toMajorUnits(amountMinor, currency));
}

/**
 * A minor-unit amount as whole dollars, or dollars and cents when it has any:
 * 3000 -> "$30", 3050 -> "$30.50", 0 -> "Free". Always a dollar sign, whatever
 * currency the amount was charged in.
 */
export function formatWholeOrCentsUSD(amountMinor: number): string {
  if (amountMinor === 0) return "Free";
  const dollars = toMajorUnits(amountMinor, "USD");
  if (dollars % 1 === 0) return `$${dollars.toFixed(0)}`;
  return `$${dollars.toFixed(2)}`;
}
