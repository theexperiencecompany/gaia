import type { z } from "zod";
import { ARTIFACT_PALETTE } from "../constants";
import type { heatmapSchema } from "../specs";
import { Figure } from "./ChartFigure";

const [FIRST_COLOUR] = ARTIFACT_PALETTE;

// a cell's tint runs from a faint wash to the full colour; text turns white once it is dark
const HEAT_FLOOR = 0.06;
const HEAT_DARK_TEXT = 0.55;

export function HeatmapView(props: z.infer<typeof heatmapSchema>) {
  const hi = Math.max(...props.values.flat()) || 1;
  return (
    <Figure title={props.title} subtitle={props.subtitle}>
      <div className="max-w-full overflow-x-auto print:overflow-visible">
        <table className="border-separate border-spacing-0.5 text-xs tabular-nums">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-background" />
              {props.columns.map((column) => (
                <th key={column} className="font-normal text-default-500">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {props.rows.map((row, i) => (
              <tr key={row}>
                <th className="sticky left-0 z-10 bg-background pr-2 text-right font-normal">
                  {row}
                </th>
                {(props.values[i] ?? []).map((value, j) => {
                  const share = value / hi;
                  const column = props.columns[j];
                  return (
                    <td
                      key={column}
                      title={`${row} ${column}: ${value}`}
                      className={`h-7 min-w-7 rounded text-center ${share > HEAT_DARK_TEXT ? "text-white" : ""}`}
                      style={{
                        background: `color-mix(in srgb, ${FIRST_COLOUR} ${Math.round((HEAT_FLOOR + share * (1 - HEAT_FLOOR)) * 100)}%, transparent)`,
                      }}
                    >
                      {value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Figure>
  );
}
