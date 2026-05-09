import {
  Avatar,
  Button,
  Checkbox,
  Chip,
  Link,
  Progress,
  Radio,
  RadioGroup,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/react";
import {
  Alert02Icon,
  ArrowDown01Icon,
  ArrowRight01Icon,
  ArrowUp01Icon,
  Cancel02Icon,
  CheckmarkCircle02Icon,
  InformationCircleIcon,
} from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";
import { useSafeTriggerAction } from "../hooks/useSafeTriggerAction";
import { ToolBanner } from "../primitives";

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

export const textContentSchema = z.object({
  text: z.string(),
  variant: z
    .enum([
      "small",
      "small-heavy",
      "body",
      "body-heavy",
      "large",
      "large-heavy",
      "h1",
      "h2",
      "caption",
      "muted",
    ])
    .optional(),
});

export const cardHeaderSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
});

export const tagSchema = z.object({
  label: z.string(),
  color: z
    .enum(["default", "primary", "success", "warning", "danger"])
    .optional(),
  size: z.enum(["sm", "md"]).optional(),
});

export const tagBlockSchema = z.object({
  labels: z.array(z.string()),
});

export const calloutSchema = z.object({
  variant: z.enum(["info", "success", "warning", "error"]),
  title: z.string(),
  description: z.string().optional(),
  width: z.enum(["sm", "md", "lg", "full"]).optional(),
  showIcon: z.boolean().optional(),
});

export const statSchema = z.object({
  label: z.string(),
  value: z.union([z.string(), z.number()]),
  unit: z.string().optional(),
  trend: z.enum(["up", "down", "neutral"]).optional(),
  trendLabel: z.string().optional(),
  size: z.enum(["sm", "md", "lg"]).optional(),
});

export const colSchema = z.object({
  header: z.string(),
  values: z.array(z.union([z.string(), z.number()])),
  type: z.enum(["string", "number", "badge", "link"]).optional(),
  align: z.enum(["start", "center", "end"]).optional(),
});

export const buttonSchema = z.object({
  label: z.string(),
  action: z.string().optional(),
  variant: z.enum(["primary", "secondary", "flat", "ghost"]).optional(),
  color: z
    .enum(["default", "primary", "danger", "warning", "success"])
    .optional(),
  url: z.string().optional(),
});

export const progressSchema = z.object({
  value: z.number(),
  max: z.number().optional(),
  color: z
    .enum(["default", "primary", "success", "warning", "danger"])
    .optional(),
  label: z.string().optional(),
  showValue: z.boolean().optional(),
  width: z.enum(["sm", "md", "lg", "full"]).optional(),
});

export const avatarSchema = z.object({
  name: z.string(),
  initials: z.string().optional(),
  image: z.string().optional(),
  color: z
    .enum(["primary", "success", "warning", "danger", "default"])
    .optional(),
  showName: z.boolean().optional(),
});

export const checkboxSchema = z.object({
  label: z.string(),
  checked: z.boolean().optional(),
  description: z.string().optional(),
});

export const radioSchema = z.object({
  label: z.string(),
  value: z.string(),
  description: z.string().optional(),
  selected: z.boolean().optional(),
});

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TEXT_VARIANT_CLASSES: Record<string, string> = {
  small: "text-xs text-zinc-400",
  "small-heavy": "text-xs font-semibold text-zinc-300",
  body: "text-sm text-zinc-300",
  "body-heavy": "text-sm font-semibold text-zinc-200",
  large: "text-base text-zinc-200",
  "large-heavy": "text-base font-bold text-zinc-100",
  h1: "text-xl font-bold text-zinc-100",
  h2: "text-lg font-semibold text-zinc-100",
  caption: "text-[11px] text-zinc-500",
  muted: "text-sm text-zinc-500",
};

const TREND_STYLES: Record<string, { color: string }> = {
  up: { color: "text-emerald-400" },
  down: { color: "text-red-400" },
  neutral: { color: "text-zinc-400" },
};

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

export function TextContentView(props: z.infer<typeof textContentSchema>) {
  const cls =
    TEXT_VARIANT_CLASSES[props.variant ?? "body"] ?? TEXT_VARIANT_CLASSES.body;
  return <p className={cls}>{props.text}</p>;
}

export function CardHeaderView(props: z.infer<typeof cardHeaderSchema>) {
  return (
    <div>
      <p className="text-sm font-semibold text-zinc-100">{props.title}</p>
      {props.subtitle && (
        <p className="text-xs text-zinc-400 mt-0.5">{props.subtitle}</p>
      )}
    </div>
  );
}

export function TagView(props: z.infer<typeof tagSchema>) {
  const heroColor =
    props.color === "default"
      ? undefined
      : (props.color as "primary" | "success" | "warning" | "danger");
  return (
    <Chip
      size={props.size === "md" ? "md" : "sm"}
      variant="flat"
      color={heroColor}
      classNames={{ base: "h-5", content: "text-[11px] px-1" }}
    >
      {props.label}
    </Chip>
  );
}

export function TagBlockView(props: z.infer<typeof tagBlockSchema>) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {(props.labels ?? []).map((label, i) => (
        <Chip
          // biome-ignore lint/suspicious/noArrayIndexKey: positional tags, labels can duplicate
          key={`${label}-${i}`}
          size="sm"
          variant="flat"
          classNames={{ base: "h-5", content: "text-[11px] px-1" }}
        >
          {label}
        </Chip>
      ))}
    </div>
  );
}

const CALLOUT_WIDTH: Record<
  NonNullable<z.infer<typeof calloutSchema>["width"]>,
  string
> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  full: "max-w-full",
};

const CALLOUT_ICON = {
  info: InformationCircleIcon,
  success: CheckmarkCircle02Icon,
  warning: Alert02Icon,
  error: Cancel02Icon,
} as const;

export function CalloutView(props: z.infer<typeof calloutSchema>) {
  const tone = props.variant === "error" ? "danger" : props.variant;
  const widthClass = CALLOUT_WIDTH[props.width ?? "lg"];
  const Icon = props.showIcon === false ? null : CALLOUT_ICON[props.variant];
  return (
    <ToolBanner
      tone={tone}
      title={props.title}
      className={widthClass}
      icon={Icon ? <Icon className="w-4 h-4" /> : undefined}
    >
      {props.description}
    </ToolBanner>
  );
}

const STAT_SIZE: Record<
  string,
  { container: string; value: string; label: string }
> = {
  sm: {
    container: "p-2 min-h-[64px] min-w-[120px]",
    value: "text-xl",
    label: "text-[11px]",
  },
  md: {
    container: "p-3 min-h-[80px] min-w-[160px]",
    value: "text-2xl",
    label: "text-xs",
  },
  lg: {
    container: "p-4 min-h-[100px] min-w-[200px]",
    value: "text-3xl",
    label: "text-sm",
  },
};

export function StatView(props: z.infer<typeof statSchema>) {
  const trendStyle = props.trend ? TREND_STYLES[props.trend] : null;
  const sz = STAT_SIZE[props.size ?? "md"];
  return (
    <div
      className={`rounded-2xl bg-zinc-800 flex flex-col justify-between ${sz.container}`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className={`${sz.label} text-zinc-500`}>{props.label}</p>
        {trendStyle && props.trendLabel && (
          <div className={`flex items-center gap-0.5 ${trendStyle.color}`}>
            {props.trend === "up" && <ArrowUp01Icon className="w-3 h-3" />}
            {props.trend === "down" && <ArrowDown01Icon className="w-3 h-3" />}
            {props.trend === "neutral" && (
              <ArrowRight01Icon className="w-3 h-3" />
            )}
            <span className="text-xs font-medium">{props.trendLabel}</span>
          </div>
        )}
      </div>
      <div className="mt-1 flex items-end gap-1">
        <span className={`${sz.value} font-bold text-zinc-100 leading-none`}>
          {typeof props.value === "number"
            ? props.value.toLocaleString()
            : props.value}
        </span>
        {props.unit && (
          <span className="text-xs text-zinc-500 mb-0.5">{props.unit}</span>
        )}
      </div>
    </div>
  );
}

export function ButtonView(props: z.infer<typeof buttonSchema>) {
  const triggerAction = useSafeTriggerAction();
  const handlePress = () => {
    if (props.url) {
      // Open the URL directly: useSafeTriggerAction is a no-op outside a
      // mounted <Renderer />, so the dispatcher path would silently drop
      // standalone (demo / preview) clicks.
      window.open(props.url, "_blank", "noopener,noreferrer");
      return;
    }
    if (props.action) triggerAction(props.action);
  };

  const variantMap: Record<string, "solid" | "flat" | "ghost" | "bordered"> = {
    primary: "solid",
    secondary: "flat",
    flat: "flat",
    ghost: "ghost",
  };

  const heroVariant = variantMap[props.variant ?? "flat"] ?? "flat";
  const heroColor =
    (props.color as "default" | "primary" | "danger" | "warning" | "success") ??
    (props.variant === "primary" ? "primary" : "default");

  return (
    <Button
      size="sm"
      variant={heroVariant}
      color={heroColor}
      onPress={handlePress}
    >
      {props.label}
    </Button>
  );
}

export function ProgressView(props: z.infer<typeof progressSchema>) {
  const max = props.max && props.max > 0 ? props.max : 100;
  const ratio = (props.value ?? 0) / max;
  const pct = Number.isFinite(ratio)
    ? Math.max(0, Math.min(100, Math.round(ratio * 100)))
    : 0;
  return (
    <div className="w-full">
      {(props.label || props.showValue) && (
        <div className="flex justify-between items-center mb-1">
          {props.label && (
            <span className="text-xs text-zinc-400">{props.label}</span>
          )}
          {props.showValue && (
            <span className="text-xs text-zinc-500">{pct}%</span>
          )}
        </div>
      )}
      <Progress
        value={pct}
        color={props.color ?? "primary"}
        size="md"
        classNames={{ track: "bg-zinc-800" }}
      />
    </div>
  );
}

export function AvatarView(props: z.infer<typeof avatarSchema>) {
  return (
    <div className="flex items-center gap-2">
      <Avatar
        name={props.name}
        src={props.image}
        showFallback
        size="sm"
        color={props.color ?? "default"}
        classNames={{ base: "shrink-0" }}
      />
      {props.showName && (
        <span className="text-sm text-zinc-300">{props.name}</span>
      )}
    </div>
  );
}

export function CheckboxView(props: z.infer<typeof checkboxSchema>) {
  return (
    <Checkbox
      isSelected={props.checked ?? false}
      isReadOnly
      size="sm"
      classNames={{ label: "text-sm text-zinc-300" }}
    >
      {props.description ? (
        <div>
          <span className="text-sm text-zinc-300">{props.label}</span>
          <p className="text-xs text-zinc-500">{props.description}</p>
        </div>
      ) : (
        props.label
      )}
    </Checkbox>
  );
}

export function RadioView(props: z.infer<typeof radioSchema>) {
  return (
    <RadioGroup value={props.selected ? props.value : ""}>
      <Radio
        value={props.value}
        description={props.description}
        classNames={{ label: "text-sm text-zinc-300" }}
      >
        {props.label}
      </Radio>
    </RadioGroup>
  );
}

// ---------------------------------------------------------------------------
// Col + Table (typed child pattern via colDef.ref)
// ---------------------------------------------------------------------------

export const colDef = defineComponent({
  name: "Col",
  description: "Data column for Table. Defines header, values array, and type.",
  props: colSchema,
  // Col renders nothing on its own — Table consumes it as typed data
  component: () => null,
});

const tableSchema = z.object({
  cols: z.array(colDef.ref),
  title: z.string().optional(),
});

export function TableView(props: z.infer<typeof tableSchema>) {
  if (!props.cols || props.cols.length === 0) return null;

  const rowCount = Math.max(...props.cols.map((c) => c.props.values.length));

  return (
    <div className="w-full max-w-2xl space-y-2">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100">{props.title}</p>
      )}
      <Table aria-label={props.title ?? "Table"} radius="lg">
        <TableHeader>
          {props.cols.map((col) => (
            <TableColumn
              key={col.props.header}
              align={
                col.props.align ??
                (col.props.type === "number" ? "end" : "start")
              }
            >
              {col.props.header}
            </TableColumn>
          ))}
        </TableHeader>
        <TableBody>
          {Array.from({ length: rowCount }, (_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: table rows indexed by position
            <TableRow key={i}>
              {props.cols.map((col) => {
                const raw = col.props.values[i];
                const val = raw ?? "";
                const type = col.props.type;

                let cell: React.ReactNode;
                if (type === "number" && typeof val === "number") {
                  cell = (
                    <span className="tabular-nums">{val.toLocaleString()}</span>
                  );
                } else if (type === "badge") {
                  cell = <Chip size="sm">{String(val)}</Chip>;
                } else if (type === "link") {
                  cell = (
                    <Link href={String(val)} isExternal size="sm">
                      {String(val)}
                    </Link>
                  );
                } else {
                  cell = String(val);
                }

                return <TableCell key={col.props.header}>{cell}</TableCell>;
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Button + Buttons (typed child pattern via buttonDef.ref)
// ---------------------------------------------------------------------------

export const buttonDef = defineComponent({
  name: "Button",
  description: "Interactive button that sends a message or triggers an action.",
  props: buttonSchema,
  component: ({ props }) => React.createElement(ButtonView, props),
});

const buttonsSchema = z.object({
  buttons: z.array(buttonDef.ref),
});

export function ButtonsView(props: z.infer<typeof buttonsSchema>) {
  return (
    <div className="flex flex-wrap gap-2">
      {props.buttons.map((btn, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: button order is positional
        <ButtonView key={i} {...btn.props} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

export const textContentDef = defineComponent({
  name: "TextContent",
  description:
    "Text with a visual variant — small, body, large, h1, h2, caption, muted, or heavy variants.",
  props: textContentSchema,
  component: ({ props }) => React.createElement(TextContentView, props),
});

export const cardHeaderDef = defineComponent({
  name: "CardHeader",
  description: "Standard card header with title and optional subtitle.",
  props: cardHeaderSchema,
  component: ({ props }) => React.createElement(CardHeaderView, props),
});

export const tagDef = defineComponent({
  name: "Tag",
  description: "Single colored chip/badge.",
  props: tagSchema,
  component: ({ props }) => React.createElement(TagView, props),
});

export const tagBlockDef = defineComponent({
  name: "TagBlock",
  description: "Inline row of tags from a plain string array.",
  props: tagBlockSchema,
  component: ({ props }) => React.createElement(TagBlockView, props),
});

export const calloutDef = defineComponent({
  name: "Callout",
  description:
    "Inline alert/notice — info, success, warning, or error. Replaces AlertBanner.",
  props: calloutSchema,
  component: ({ props }) => React.createElement(CalloutView, props),
});

export const statDef = defineComponent({
  name: "Stat",
  description: "Single KPI: label, large value, optional unit and trend.",
  props: statSchema,
  component: ({ props }) => React.createElement(StatView, props),
});

export const tableDef = defineComponent({
  name: "Table",
  description:
    "Data table built from Col children. Each Col defines a header + values array.",
  props: tableSchema,
  component: ({ props }) => React.createElement(TableView, props),
});

export const buttonsDef = defineComponent({
  name: "Buttons",
  description: "A row of Button components.",
  props: buttonsSchema,
  component: ({ props }) => React.createElement(ButtonsView, props),
});

export const progressDef = defineComponent({
  name: "Progress",
  description: "Progress bar with optional label and value display.",
  props: progressSchema,
  component: ({ props }) => React.createElement(ProgressView, props),
});

export const avatarDef = defineComponent({
  name: "Avatar",
  description: "User avatar with name label.",
  props: avatarSchema,
  component: ({ props }) => React.createElement(AvatarView, props),
});

export const checkboxDef = defineComponent({
  name: "Checkbox",
  description: "Read-only checkbox with label and optional description.",
  props: checkboxSchema,
  component: ({ props }) => React.createElement(CheckboxView, props),
});

export const radioDef = defineComponent({
  name: "Radio",
  description: "Single radio option — use inside Stack for a group.",
  props: radioSchema,
  component: ({ props }) => React.createElement(RadioView, props),
});
