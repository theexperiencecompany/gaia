import {
  describeArtifactComponent,
  kanbanSchema,
  statsSchema,
} from "@gaia/artifacts/specs";
import { Chip } from "@heroui/react";
import { ArrowDown01Icon, ArrowUp01Icon } from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import { GroundedText } from "../GroundedText";

// Views stay file-private: this module's surface is the defs (react-refresh/only-export-components).

const SENTIMENT_TEXT: Record<string, string> = {
  good: "text-success",
  bad: "text-danger",
};

function Trend({ trend }: { trend: string | null | undefined }) {
  if (trend === "up")
    return <ArrowUp01Icon className="size-4 shrink-0" aria-label="up" />;
  if (trend === "down")
    return <ArrowDown01Icon className="size-4 shrink-0" aria-label="down" />;
  return null;
}

export const statsDef = defineComponent({
  name: "Stats",
  description: describeArtifactComponent("Stats"),
  props: statsSchema,
  component: ({ props }) => (
    // columns follow the card's width, not the window's: beside the open viewer a chat card is narrow
    <div
      data-slot="stats"
      className="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-3"
    >
      {props.items.map(([label, value, note, trend, sentiment]) => (
        <div
          key={`${label} ${value}`}
          className="flex flex-col gap-1 rounded-2xl bg-default p-4"
        >
          <span className="text-sm text-muted">{label}</span>
          <span className="text-3xl font-semibold tracking-tight text-foreground tabular-nums">
            <GroundedText text={value} />
          </span>
          {note ? (
            <span
              className={`flex items-center gap-1 text-sm ${SENTIMENT_TEXT[sentiment ?? ""] ?? "text-muted"}`}
            >
              <Trend trend={trend} />
              <GroundedText text={note} />
            </span>
          ) : null}
        </div>
      ))}
    </div>
  ),
});

export const kanbanDef = defineComponent({
  name: "Kanban",
  description: describeArtifactComponent("Kanban"),
  props: kanbanSchema,
  component: ({ props }) => (
    <div className="grid auto-cols-[minmax(220px,1fr)] grid-flow-col gap-3 overflow-x-auto print:overflow-visible">
      {props.columns.map(([title, cards]) => (
        <div
          key={title}
          className="flex flex-col gap-2 rounded-2xl bg-default p-3"
        >
          <p className="flex justify-between text-sm font-semibold">
            {title}
            <span className="text-muted tabular-nums">{cards.length}</span>
          </p>
          {cards.map(([cardTitle, meta, tag]) => (
            <div
              key={cardTitle}
              className="flex flex-col gap-1 rounded-2xl bg-background p-3 text-sm"
            >
              <span className="font-medium">{cardTitle}</span>
              {meta ? <span className="text-xs text-muted">{meta}</span> : null}
              {tag ? (
                <Chip size="sm" variant="soft" className="self-start">
                  <Chip.Label>{tag}</Chip.Label>
                </Chip>
              ) : null}
            </div>
          ))}
        </div>
      ))}
    </div>
  ),
});
