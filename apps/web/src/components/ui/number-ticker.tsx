"use client";

import NumberFlow from "@number-flow/react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

type NumberTickerProps = {
  value: number;
  className?: string;
  decimalPlaces?: number;
  prefix?: string;
  suffix?: string;
  delay?: number;
};

export function NumberTicker({
  value,
  className,
  decimalPlaces = 0,
  prefix,
  suffix,
  delay = 0,
}: NumberTickerProps) {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    const timeout = setTimeout(() => setDisplayValue(value), delay);
    return () => clearTimeout(timeout);
  }, [value, delay]);

  return (
    <NumberFlow
      value={displayValue}
      prefix={prefix}
      suffix={suffix}
      format={{
        minimumFractionDigits: decimalPlaces,
        maximumFractionDigits: decimalPlaces,
      }}
      className={cn("inline-block tabular-nums text-zinc-100", className)}
      transformTiming={{ duration: 750, easing: "ease-out" }}
      spinTiming={{ duration: 750, easing: "ease-out" }}
    />
  );
}
