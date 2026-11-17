import { ProgressBar } from "@heroui/react";
import type { z } from "zod";
import type { funnelSchema } from "../specs";
import { Figure } from "./ChartFigure";

export function FunnelView(props: z.infer<typeof funnelSchema>) {
  const top = props.stages[0]?.[1] || 1;
  return (
    <Figure title={props.title} subtitle={props.subtitle}>
      {props.stages.map(([label, value], i) => {
        const previous = props.stages[i - 1]?.[1];
        const carried = previous
          ? `${Math.round((value / previous) * 100)}%`
          : null;
        return (
          <div key={label} className="flex flex-col gap-1">
            <div className="flex justify-between gap-3 text-sm">
              <span>{label}</span>
              <span className="flex gap-3 text-muted tabular-nums">
                <span>{value.toLocaleString("en")}</span>
                {carried ? (
                  <span className="text-zinc-500">{carried}</span>
                ) : null}
              </span>
            </div>
            <ProgressBar
              aria-label={label}
              value={(value / top) * 100}
              size="md"
              color="accent"
            >
              <ProgressBar.Track>
                <ProgressBar.Fill />
              </ProgressBar.Track>
            </ProgressBar>
          </div>
        );
      })}
    </Figure>
  );
}
