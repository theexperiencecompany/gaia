import type { z } from "zod";
import { NumberTicker } from "@/components/ui/number-ticker";
import type { numberTickerSchema } from "../promptSpecs";

const NUMBER_TICKER_SIZE: Record<
  string,
  { container: string; value: string; unit: string }
> = {
  sm: { container: "p-3 min-w-[120px]", value: "text-2xl", unit: "text-xs" },
  md: { container: "p-4 min-w-[160px]", value: "text-3xl", unit: "text-sm" },
  lg: { container: "p-5 min-w-[200px]", value: "text-4xl", unit: "text-base" },
};

export function NumberTickerView(props: z.infer<typeof numberTickerSchema>) {
  const isDecimal = props.value % 1 !== 0;
  const sz = NUMBER_TICKER_SIZE[props.size ?? "md"];
  return (
    <div
      className={`rounded-2xl bg-zinc-800 text-center w-fit ${sz.container}`}
    >
      {props.label && (
        <p className="text-xs text-zinc-500 mb-2">{props.label}</p>
      )}
      <div className="flex items-end justify-center gap-1">
        <span className={`${sz.value} font-semibold text-zinc-100`}>
          <NumberTicker value={props.value} decimalPlaces={isDecimal ? 1 : 0} />
        </span>
        {props.unit && (
          <span className={`${sz.unit} text-zinc-500 mb-0.5`}>
            {props.unit}
          </span>
        )}
      </div>
    </div>
  );
}
