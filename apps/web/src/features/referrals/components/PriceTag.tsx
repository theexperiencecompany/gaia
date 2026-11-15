import { cn } from "@/lib/utils";
import { REFERRAL_UI_COPY } from "../referralCopy";

const SIZES = {
  md: { price: "text-4xl", unit: "text-sm" },
  lg: { price: "text-6xl", unit: "text-base" },
} as const;

interface PriceTagProps {
  /** A formatted amount with its symbol, "$15". */
  price: string;
  /** The struck-through regular price, when the tag shows a discount. */
  was?: string;
  size?: keyof typeof SIZES;
}

/**
 * One typographic unit for a price: symbol and digits share Inter's tabular
 * figures, so "$" sits on the digits' baseline instead of a display face's.
 */
export function PriceTag({ price, was, size = "lg" }: PriceTagProps) {
  const sizes = SIZES[size];
  return (
    <p className="flex items-baseline gap-1.5 font-sans tabular-nums">
      {was && (
        <span className={cn("mr-1 text-zinc-500 line-through", sizes.unit)}>
          {was}
        </span>
      )}
      <span
        className={cn(
          "leading-none font-semibold tracking-[-0.035em] text-zinc-50",
          sizes.price,
        )}
      >
        {price}
      </span>
      <span className={cn("text-zinc-400", sizes.unit)}>
        {REFERRAL_UI_COPY.perMonth}
      </span>
    </p>
  );
}
