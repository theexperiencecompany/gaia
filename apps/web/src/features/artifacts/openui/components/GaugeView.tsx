import type { z } from "zod";
import { ARTIFACT_PALETTE } from "../constants";
import { GroundedText } from "../GroundedText";
import type { gaugeSchema } from "../specs";

const [FIRST_COLOUR] = ARTIFACT_PALETTE;

const GAUGE_ARC = "M20 115 A90 90 0 0 1 200 115";
const GAUGE_LENGTH = Math.PI * 90;

export function GaugeView(props: z.infer<typeof gaugeSchema>) {
  const share =
    props.max > 0 ? Math.min(1, Math.max(0, props.value / props.max)) : 0;
  return (
    <figure className="flex flex-col items-center gap-2">
      <figcaption className="self-start font-semibold text-foreground">
        <GroundedText text={props.title} />
      </figcaption>
      <svg
        viewBox="0 0 220 130"
        width="220"
        role="img"
        aria-label={`${props.value}${props.suffix ?? ""}`}
      >
        <path
          d={GAUGE_ARC}
          fill="none"
          className="stroke-default-200"
          strokeWidth="16"
          strokeLinecap="round"
        />
        <path
          d={GAUGE_ARC}
          fill="none"
          stroke={FIRST_COLOUR}
          strokeWidth="16"
          strokeLinecap="round"
          strokeDasharray={`${share * GAUGE_LENGTH} ${GAUGE_LENGTH}`}
        />
        <text
          x="110"
          y="100"
          textAnchor="middle"
          fontSize="30"
          fontWeight="600"
          className="fill-foreground"
        >
          {props.value}
          {props.suffix}
        </text>
      </svg>
      <span className="text-sm text-default-500">
        <GroundedText text={props.label} />
      </span>
    </figure>
  );
}
