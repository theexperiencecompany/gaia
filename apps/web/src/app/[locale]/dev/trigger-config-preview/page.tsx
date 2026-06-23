"use client";

import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Input } from "@heroui/input";
import { NumberInput } from "@heroui/number-input";
import { Select, SelectItem } from "@heroui/select";
import { Switch } from "@heroui/switch";
import { Tab, Tabs } from "@heroui/tabs";
import { useState } from "react";

import { ChevronDown } from "@/components/shared/icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

// =============================================================================
// Dev playground: brainstorm trigger-config UIs. Every trigger we support is
// described as a list of fields, then rendered in three layout versions so we
// can compare. Rendered at the workflow modal's width, outside the modal.
// =============================================================================

type Option = { id: string; name: string };

type Field =
  | {
      type: "multiselect";
      key: string;
      label: string;
      placeholder: string;
      hint?: string;
      options: Option[];
    }
  | {
      type: "segmented";
      key: string;
      label: string;
      presets: number[];
      defaultValue: number;
    }
  | {
      type: "tags";
      key: string;
      label: string;
      placeholder: string;
      prefix?: string;
    }
  | { type: "toggle"; key: string; label: string; hint?: string };

interface TriggerSpec {
  integrationId: string;
  event: string;
  description: string;
  fields: Field[];
}

const TRIGGERS: TriggerSpec[] = [
  {
    integrationId: "gmail",
    event: "New email in inbox",
    description: "Runs whenever new email arrives in your inbox.",
    fields: [
      {
        type: "segmented",
        key: "interval",
        label: "Check my inbox every",
        presets: [5, 15, 30, 60],
        defaultValue: 15,
      },
    ],
  },
  {
    integrationId: "googlecalendar",
    event: "Event starting soon",
    description: "Runs shortly before a calendar event begins.",
    fields: [
      {
        type: "multiselect",
        key: "calendars",
        label: "Calendars",
        placeholder: "Select calendars to monitor",
        hint: "Leave empty to watch all calendars",
        options: [
          { id: "primary", name: "Primary" },
          { id: "work", name: "Work" },
          { id: "personal", name: "Personal" },
          { id: "family", name: "Family" },
        ],
      },
      {
        type: "segmented",
        key: "lead",
        label: "Remind me before",
        presets: [5, 15, 30, 60],
        defaultValue: 15,
      },
      {
        type: "toggle",
        key: "allday",
        label: "Include all-day events",
        hint: "Trigger for events without a set time",
      },
    ],
  },
  {
    integrationId: "slack",
    event: "New Slack message",
    description: "Runs when a new message is posted in a channel.",
    fields: [
      {
        type: "multiselect",
        key: "channels",
        label: "Channels",
        placeholder: "Select channels",
        hint: "Leave empty to watch every channel",
        options: [
          { id: "general", name: "#general" },
          { id: "engineering", name: "#engineering" },
          { id: "design", name: "#design" },
          { id: "support", name: "#support" },
        ],
      },
      {
        type: "toggle",
        key: "bots",
        label: "Exclude bot messages",
        hint: "Ignore messages posted by bots",
      },
      {
        type: "toggle",
        key: "dms",
        label: "Exclude direct messages",
        hint: "Ignore 1:1 conversations",
      },
    ],
  },
  {
    integrationId: "github",
    event: "New commit",
    description: "Runs when a new commit is pushed to a repository.",
    fields: [
      {
        type: "tags",
        key: "repos",
        label: "Repositories",
        placeholder: "octocat/hello-world",
        prefix: "github.com/",
      },
    ],
  },
  {
    integrationId: "linear",
    event: "Issue created",
    description: "Runs when a new issue is created.",
    fields: [
      {
        type: "multiselect",
        key: "teams",
        label: "Teams",
        placeholder: "Select teams",
        hint: "Leave empty to watch every team",
        options: [
          { id: "eng", name: "Engineering" },
          { id: "design", name: "Design" },
          { id: "product", name: "Product" },
        ],
      },
    ],
  },
  {
    integrationId: "notion",
    event: "Database item added",
    description: "Runs when a new item is added to a database.",
    fields: [
      {
        type: "multiselect",
        key: "databases",
        label: "Databases",
        placeholder: "Select databases",
        options: [
          { id: "tasks", name: "Tasks" },
          { id: "docs", name: "Docs" },
          { id: "crm", name: "CRM" },
        ],
      },
    ],
  },
  {
    integrationId: "asana",
    event: "Task added",
    description: "Runs when a task is added to a project.",
    fields: [
      {
        type: "multiselect",
        key: "projects",
        label: "Projects",
        placeholder: "Select projects",
        options: [
          { id: "roadmap", name: "Roadmap" },
          { id: "bugs", name: "Bugs" },
          { id: "marketing", name: "Marketing" },
        ],
      },
    ],
  },
  {
    integrationId: "googlesheets",
    event: "New row added",
    description: "Runs when a row is added to a spreadsheet.",
    fields: [
      {
        type: "multiselect",
        key: "sheets",
        label: "Spreadsheets",
        placeholder: "Select spreadsheets",
        options: [
          { id: "budget", name: "Budget" },
          { id: "leads", name: "Leads" },
          { id: "inventory", name: "Inventory" },
        ],
      },
    ],
  },
];

const UNIT_FACTOR = { minutes: 1, hours: 60, days: 1440 } as const;
type TimeUnit = keyof typeof UNIT_FACTOR;

function plural(n: number, word: string): string {
  return `${n} ${n === 1 ? word : `${word}s`}`;
}

function describeMinutes(mins: number): string {
  if (mins % 1440 === 0) return plural(mins / 1440, "day");
  if (mins % 60 === 0) return plural(mins / 60, "hour");
  return plural(mins, "minute");
}

function triggerIcon(integrationId: string, size = 24) {
  return getToolCategoryIcon(integrationId, {
    width: size,
    height: size,
    showBackground: false,
  });
}

// =============================================================================
// Bare controls (no label — the layout supplies the label)
// =============================================================================

function MultiSelectControl({
  field,
}: {
  field: Extract<Field, { type: "multiselect" }>;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  return (
    <Select
      aria-label={field.label}
      placeholder={field.placeholder}
      selectionMode="multiple"
      selectedKeys={selected}
      onSelectionChange={(keys) => setSelected(keys as Set<string>)}
      items={field.options}
      className="w-full"
    >
      {(o) => <SelectItem key={o.id}>{o.name}</SelectItem>}
    </Select>
  );
}

function SegmentedControl({
  field,
  withHelper,
}: {
  field: Extract<Field, { type: "segmented" }>;
  withHelper?: boolean;
}) {
  const [value, setValue] = useState(field.defaultValue);
  const [customMode, setCustomMode] = useState(
    !field.presets.includes(field.defaultValue),
  );
  const [amount, setAmount] = useState(field.defaultValue);
  const [unit, setUnit] = useState<TimeUnit>("minutes");

  const applyCustom = (nextAmount: number, nextUnit: TimeUnit) => {
    const amt = Number.isNaN(nextAmount) ? 1 : Math.max(1, nextAmount);
    setAmount(amt);
    setUnit(nextUnit);
    setValue(amt * UNIT_FACTOR[nextUnit]);
  };

  return (
    <div className="space-y-2">
      <Tabs
        aria-label={field.label}
        selectedKey={customMode ? "custom" : String(value)}
        onSelectionChange={(k) => {
          const key = String(k);
          if (key === "custom") {
            setCustomMode(true);
          } else {
            setCustomMode(false);
            setValue(Number(key));
          }
        }}
        fullWidth
        classNames={{
          tabList: "rounded-xl bg-zinc-800/60 p-1",
          cursor: "rounded-lg bg-zinc-700 shadow-sm",
          tabContent:
            "font-medium text-zinc-400 group-data-[selected=true]:text-white",
          panel: "hidden",
        }}
      >
        {field.presets.map((p) => (
          <Tab key={String(p)} title={p === 60 ? "1h" : `${p}m`} />
        ))}
        <Tab key="custom" title="Custom" />
      </Tabs>
      {customMode && (
        <div className="flex items-center gap-2">
          <NumberInput
            aria-label={`Custom ${field.label}`}
            minValue={1}
            hideStepper
            value={amount}
            onValueChange={(n) => applyCustom(n, unit)}
            className="flex-1"
          />
          <Select
            aria-label="Unit"
            selectedKeys={new Set([unit])}
            onSelectionChange={(keys) =>
              applyCustom(amount, Array.from(keys)[0] as TimeUnit)
            }
            disallowEmptySelection
            className="w-32 shrink-0"
            classNames={{ popoverContent: "min-w-fit" }}
          >
            <SelectItem key="minutes">minutes</SelectItem>
            <SelectItem key="hours">hours</SelectItem>
            <SelectItem key="days">days</SelectItem>
          </Select>
        </div>
      )}
      {withHelper && (
        <p className="text-xs text-zinc-500">Every {describeMinutes(value)}.</p>
      )}
    </div>
  );
}

function TagsControl({ field }: { field: Extract<Field, { type: "tags" }> }) {
  const [values, setValues] = useState<string[]>([]);
  const [input, setInput] = useState("");

  const add = () => {
    const v = input.trim();
    if (v && !values.includes(v)) setValues([...values, v]);
    setInput("");
  };

  return (
    <div className="space-y-2">
      <Input
        aria-label={field.label}
        value={input}
        onValueChange={setInput}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
        placeholder={field.placeholder}
        startContent={
          field.prefix ? (
            <span className="pointer-events-none shrink-0 text-sm text-zinc-500">
              {field.prefix}
            </span>
          ) : undefined
        }
      />
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <Chip
              key={v}
              variant="flat"
              onClose={() => setValues(values.filter((x) => x !== v))}
              classNames={{ content: "font-mono text-xs" }}
            >
              {v}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

function Control({ field, compact }: { field: Field; compact?: boolean }) {
  if (field.type === "multiselect") return <MultiSelectControl field={field} />;
  if (field.type === "segmented")
    return <SegmentedControl field={field} withHelper={!compact} />;
  if (field.type === "tags") return <TagsControl field={field} />;
  return null;
}

// =============================================================================
// Event selector (shared header for all versions)
// =============================================================================

function EventSelector({ spec }: { spec: TriggerSpec }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-800/60 px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <div className="shrink-0">{triggerIcon(spec.integrationId)}</div>
        <div className="flex min-w-0 flex-col">
          <span className="text-xs text-zinc-400">Event</span>
          <span className="truncate text-sm font-medium text-white">
            {spec.event}
          </span>
        </div>
      </div>
      <ChevronDown className="size-4 shrink-0 text-zinc-500" />
    </div>
  );
}

function ToggleRow({ field }: { field: Extract<Field, { type: "toggle" }> }) {
  const [on, setOn] = useState(false);
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium text-zinc-200">{field.label}</span>
        {field.hint ? (
          <span className="text-xs text-zinc-500">{field.hint}</span>
        ) : null}
      </div>
      <Switch size="sm" isSelected={on} onValueChange={setOn} />
    </div>
  );
}

// =============================================================================
// Versions
// =============================================================================

function VersionA({ spec }: { spec: TriggerSpec }) {
  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <EventSelector spec={spec} />
        <p className="px-1 text-xs text-zinc-500">{spec.description}</p>
      </div>
      {spec.fields.map((field) =>
        field.type === "toggle" ? (
          <ToggleRow key={field.key} field={field} />
        ) : (
          <div key={field.key} className="space-y-2">
            <span className="text-sm font-medium text-zinc-300">
              {field.label}
            </span>
            <Control field={field} />
          </div>
        ),
      )}
    </div>
  );
}

function VersionB({ spec }: { spec: TriggerSpec }) {
  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <EventSelector spec={spec} />
        <p className="px-1 text-xs text-zinc-500">{spec.description}</p>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Settings
        </span>
        <Divider className="flex-1 bg-zinc-800" />
      </div>
      {spec.fields.map((field) =>
        field.type === "toggle" ? (
          <ToggleRow key={field.key} field={field} />
        ) : (
          <div key={field.key} className="space-y-2">
            <span className="text-sm font-medium text-zinc-300">
              {field.label}
            </span>
            <Control field={field} />
          </div>
        ),
      )}
    </div>
  );
}

function VersionC({ spec }: { spec: TriggerSpec }) {
  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <EventSelector spec={spec} />
        <p className="px-1 text-xs text-zinc-500">{spec.description}</p>
      </div>
      <div className="divide-y divide-zinc-800 overflow-hidden rounded-2xl bg-zinc-800/40">
        {spec.fields.map((field) => (
          <CardRow key={field.key} field={field} />
        ))}
      </div>
    </div>
  );
}

// One settings row: label (+ optional hint) on the left, control on the right,
// all controls sharing one width so they line up — the Notion settings pattern.
function CardRow({ field }: { field: Field }) {
  if (field.type === "toggle") {
    return (
      <div className="px-4 py-3.5">
        <ToggleRow field={field} />
      </div>
    );
  }

  return (
    <div className="flex items-start justify-between gap-4 px-4 py-3.5">
      {/* min-h matches the control's first row so the label sits centered when
          the control is a single row, and stays top-aligned when it grows
          (e.g. the custom input expands below the presets). */}
      <div className="flex min-h-10 min-w-0 flex-col justify-center gap-0.5">
        <span className="text-sm font-medium text-zinc-200">{field.label}</span>
        {field.type === "multiselect" && field.hint ? (
          <span className="text-xs text-zinc-500">{field.hint}</span>
        ) : null}
      </div>
      <div className="w-[19rem] shrink-0">
        <Control field={field} compact />
      </div>
    </div>
  );
}

const VERSIONS = {
  a: { label: "Flat stack", node: VersionA },
  b: { label: "Settings group", node: VersionB },
  c: { label: "List rows", node: VersionC },
} as const;

type VersionKey = keyof typeof VERSIONS;

export default function TriggerConfigPreviewPage() {
  const [triggerIdx, setTriggerIdx] = useState(0);
  const [version, setVersion] = useState<VersionKey>("a");

  const spec = TRIGGERS[triggerIdx];
  const Version = VERSIONS[version].node;

  return (
    <div className="min-h-screen bg-primary-bg p-8">
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        <div>
          <h1 className="text-lg font-semibold text-white">
            Trigger config — UI brainstorm
          </h1>
          <p className="text-sm text-zinc-400">
            Every trigger, three layout versions. All controls are live.
          </p>
        </div>

        <Tabs
          aria-label="Trigger"
          selectedKey={String(triggerIdx)}
          onSelectionChange={(k) => setTriggerIdx(Number(k))}
          classNames={{ tabList: "flex-wrap" }}
        >
          {TRIGGERS.map((t, i) => (
            <Tab
              key={String(i)}
              title={
                <div className="flex items-center gap-2">
                  {triggerIcon(t.integrationId, 18)}
                  <span>{t.event}</span>
                </div>
              }
            />
          ))}
        </Tabs>

        <Tabs
          aria-label="Version"
          selectedKey={version}
          onSelectionChange={(k) => setVersion(k as VersionKey)}
          color="primary"
        >
          {(Object.keys(VERSIONS) as VersionKey[]).map((k) => (
            <Tab key={k} title={VERSIONS[k].label} />
          ))}
        </Tabs>

        {/* Width matches the workflow modal's form column */}
        <div className="rounded-3xl bg-secondary-bg p-6">
          <Version spec={spec} />
        </div>
      </div>
    </div>
  );
}
