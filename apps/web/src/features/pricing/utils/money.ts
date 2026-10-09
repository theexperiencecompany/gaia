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

function moneyFormatter(
  code: string,
  trailingZeroDisplay: "auto" | "stripIfInteger" = "auto",
): Intl.NumberFormat {
  const key = `${code}:${trailingZeroDisplay}`;
  const cached = MONEY_FORMATTERS.get(key);
  if (cached) return cached;
  const formatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: code,
    currencyDisplay: "narrowSymbol",
    trailingZeroDisplay,
  });
  MONEY_FORMATTERS.set(key, formatter);
  return formatter;
}

export function isWellFormedCurrency(code: string): boolean {
  return WELL_FORMED_CURRENCY.test(code);
}

/** Digits after the decimal point in the currency's major unit. */
export function currencyExponent(code: string): number {
  if (!isWellFormedCurrency(code)) return ISO_4217_DEFAULT_EXPONENT;
  return (
    moneyFormatter(code).resolvedOptions().maximumFractionDigits ??
    ISO_4217_DEFAULT_EXPONENT
  );
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
 * A minor-unit amount in its currency, dropping the fraction when it is whole:
 * 3000 USD -> "$30", 3050 USD -> "$30.50", 3000 EUR -> "€30", 0 -> "Free".
 */
export function formatWholeOrCents(
  amountMinor: number,
  currency: string,
): string {
  if (amountMinor === 0) return "Free";
  return moneyFormatter(currency, "stripIfInteger").format(
    toMajorUnits(amountMinor, currency),
  );
}
