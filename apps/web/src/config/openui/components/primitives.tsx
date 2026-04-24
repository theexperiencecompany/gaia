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
import { ArrowDown01Icon, ArrowRight01Icon, ArrowUp01Icon } from "@icons";
import { defineComponent, useTriggerAction } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";

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
});

export const statSchema = z.object({
  label: z.string(),
  value: z.union([z.string(), z.number()]),
  unit: z.string().optional(),
  trend: z.enum(["up", "down", "neutral"]).optional(),
  trendLabel: z.string().optional(),
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

const CALLOUT_STYLES: Record<
  string,
  { inner: string; text: string; accent: string }
> = {
  info: {
    inner: "bg-blue-400/10",
    text: "text-blue-400",
    accent: "text-blue-300",
  },
  success: {
    inner: "bg-emerald-400/10",
    text: "text-emerald-400",
    accent: "text-emerald-300",
  },
  warning: {
    inner: "bg-amber-400/10",
    text: "text-amber-400",
    accent: "text-amber-300",
  },
  error: {
    inner: "bg-red-400/10",
    text: "text-red-400",
    accent: "text-red-300",
  },
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
      {(props.labels ?? []).map((label) => (
        <Chip
          key={label}
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

export function CalloutView(props: z.infer<typeof calloutSchema>) {
  const style = CALLOUT_STYLES[props.variant] ?? CALLOUT_STYLES.info;
  return (
    <div className={`rounded-xl ${style.inner} p-3 w-full max-w-lg`}>
      <p className={`text-sm font-semibold ${style.text}`}>{props.title}</p>
      {props.description && (
        <p className={`text-xs mt-1 ${style.accent}`}>{props.description}</p>
      )}
    </div>
  );
}

export function StatView(props: z.infer<typeof statSchema>) {
  const trendStyle = props.trend ? TREND_STYLES[props.trend] : null;
  return (
    <div className="rounded-xl bg-zinc-900 p-3 flex flex-col justify-between min-h-[80px]">
      <p className="text-xs text-zinc-500">{props.label}</p>
      <div className="mt-1">
        <div className="flex items-end gap-1">
          <span className="text-2xl font-bold text-zinc-100 leading-none">
            {typeof props.value === "number"
              ? props.value.toLocaleString()
              : props.value}
          </span>
          {props.unit && (
            <span className="text-xs text-zinc-500 mb-0.5">{props.unit}</span>
          )}
        </div>
        {trendStyle && props.trendLabel ? (
          <div className={`flex items-center gap-1 mt-1 ${trendStyle.color}`}>
            {props.trend === "up" && <ArrowUp01Icon className="w-3 h-3" />}
            {props.trend === "down" && <ArrowDown01Icon className="w-3 h-3" />}
            {props.trend === "neutral" && (
              <ArrowRight01Icon className="w-3 h-3" />
            )}
            <span className="text-xs font-medium">{props.trendLabel}</span>
          </div>
        ) : (
          <div className="mt-1 h-4" />
        )}
      </div>
    </div>
  );
}

export function ButtonView(props: z.infer<typeof buttonSchema>) {
  const triggerAction = useTriggerAction();
  const handlePress = () => {
    if (props.url) {
      triggerAction(props.label, undefined, {
        type: "open_url",
        params: { url: props.url },
      });
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
  const max = props.max ?? 100;
  const pct = Math.min(100, Math.round((props.value / max) * 100));
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
        size="sm"
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
  striped: z.boolean().optional(),
});

export function TableView(props: z.infer<typeof tableSchema>) {
  if (!props.cols || props.cols.length === 0) return null;

  const rowCount = Math.max(...props.cols.map((c) => c.props.values.length));

  return (
    <div className="w-full">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <Table
        removeWrapper
        isStriped={props.striped}
        classNames={{
          th: "bg-zinc-900 text-zinc-400 text-xs font-medium",
          td: "text-sm text-zinc-300 py-2",
          tr: "border-b border-zinc-800/50",
        }}
      >
        <TableHeader>
          {props.cols.map((col) => (
            <TableColumn
              key={col.props.header}
              align={
                col.props.align ??
                (col.props.type === "number" ? "end" : "start")
              }
              className="text-xs"
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
                  cell = (
                    <Chip
                      size="sm"
                      variant="flat"
                      classNames={{ content: "text-xs" }}
                    >
                      {String(val)}
                    </Chip>
                  );
                } else if (type === "link") {
                  cell = (
                    <Link
                      href={String(val)}
                      isExternal
                      size="sm"
                      className="text-blue-400 text-xs"
                    >
                      {String(val)}
                    </Link>
                  );
                } else {
                  cell = String(val);
                }

                return (
                  <TableCell
                    key={col.props.header}
                    className={col.props.type === "number" ? "text-right" : ""}
                  >
                    {cell}
                  </TableCell>
                );
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
