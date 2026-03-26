import {
  AccordionItem,
  Avatar,
  AvatarGroup,
  Chip,
  Accordion as HeroAccordion,
  Kbd,
  Progress,
  Radio,
  RadioGroup,
  Tab,
  Tabs,
} from "@heroui/react";
import {
  ArrowDown01Icon,
  ArrowRight01Icon,
  Cancel01Icon,
  CheckmarkCircle01Icon,
  File01Icon,
  Folder02Icon,
} from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

export const dataCardSchema = z.object({
  title: z.string(),
  fields: z.array(z.object({ label: z.string(), value: z.string() })),
});

export const resultListSchema = z.object({
  items: z.array(
    z.object({
      title: z.string(),
      subtitle: z.string().optional(),
      body: z.string().optional(),
      url: z.string().optional(),
      badge: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

export const comparisonTableSchema = z.object({
  leftLabel: z.string(),
  rightLabel: z.string(),
  rows: z.array(
    z.object({
      label: z.string(),
      left: z.string(),
      right: z.string(),
      highlight: z.boolean().optional(),
    }),
  ),
  title: z.string().optional(),
});

export const statusCardSchema = z.object({
  title: z.string(),
  status: z.enum(["success", "error", "warning", "info", "pending"]),
  message: z.string().optional(),
  detail: z.string().optional(),
});

export const actionCardSchema = z.object({
  title: z.string(),
  description: z.string().optional(),
  actions: z
    .array(
      z.object({
        label: z.string(),
        type: z.literal("continue_conversation"),
        value: z.string(),
      }),
    )
    .optional(),
});

export const tagGroupSchema = z.object({
  tags: z.array(
    z.object({
      label: z.string(),
      color: z
        .enum(["default", "primary", "success", "warning", "danger"])
        .optional(),
    }),
  ),
  title: z.string().optional(),
});

export const fileTreeSchema = z.object({
  items: z.array(
    z.object({
      path: z.string(),
      type: z.enum(["file", "dir"]),
      size: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

export const accordionSchema = z.object({
  items: z.array(z.object({ label: z.string(), content: z.string() })),
  title: z.string().optional(),
});

export const tabsBlockSchema = z.object({
  tabs: z.array(z.object({ label: z.string(), content: z.string() })),
});

export const progressListSchema = z.object({
  items: z.array(
    z.object({
      label: z.string(),
      value: z.number(),
      max: z.number().optional(),
      color: z
        .enum(["default", "primary", "success", "warning", "danger"])
        .optional(),
    }),
  ),
  title: z.string().optional(),
});

export const selectableListSchema = z.object({
  options: z.array(
    z.object({
      label: z.string(),
      description: z.string().optional(),
      value: z.string(),
      badge: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
  description: z.string().optional(),
});

export const avatarListSchema = z.object({
  items: z.array(
    z.object({
      name: z.string(),
      role: z.string().optional(),
      description: z.string().optional(),
      initials: z.string().optional(),
      color: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

export const kbdBlockSchema = z.object({
  shortcuts: z.array(
    z.object({ keys: z.array(z.string()), description: z.string() }),
  ),
  title: z.string().optional(),
});

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const STATUS_CHIP_COLOR: Record<
  string,
  "success" | "danger" | "warning" | "default"
> = {
  success: "success",
  error: "danger",
  warning: "warning",
  pending: "default",
};

const STATUS_DOT: Record<string, string> = {
  success: "bg-emerald-400",
  error: "bg-red-400",
  warning: "bg-amber-400",
  info: "bg-blue-400",
  pending: "bg-zinc-500",
};

// ---------------------------------------------------------------------------
// FileTree helpers
// ---------------------------------------------------------------------------

type FileTreeNode = {
  name: string;
  type: "file" | "dir";
  size?: string;
  children: Record<string, FileTreeNode>;
};

function buildFileTree(
  items: Array<{ path: string; type: "file" | "dir"; size?: string }>,
): Record<string, FileTreeNode> {
  const root: Record<string, FileTreeNode> = {};
  for (const item of items) {
    const parts = item.path.replace(/\/$/, "").split("/").filter(Boolean);
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      if (!current[part]) {
        current[part] = {
          name: part,
          type: isLast ? item.type : "dir",
          size: isLast ? item.size : undefined,
          children: {},
        };
      }
      current = current[part].children;
    }
  }
  return root;
}

function FileTreeNodeRow({
  node,
  depth,
}: {
  node: FileTreeNode;
  depth: number;
}) {
  const [open, setOpen] = React.useState(true);
  const isDir = node.type === "dir";
  const hasChildren = Object.keys(node.children).length > 0;

  return (
    <div>
      <div
        className="flex items-center justify-between gap-2 px-2 py-1 rounded-lg hover:bg-zinc-800/60 transition cursor-pointer select-none"
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        onClick={isDir && hasChildren ? () => setOpen((o) => !o) : undefined}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {isDir && hasChildren ? (
            open ? (
              <ArrowDown01Icon className="w-3 h-3 text-zinc-500 shrink-0" />
            ) : (
              <ArrowRight01Icon className="w-3 h-3 text-zinc-500 shrink-0" />
            )
          ) : (
            <span className="w-3 h-3 shrink-0" />
          )}
          {isDir ? (
            <Folder02Icon className="w-4 h-4 text-[#00bbff] shrink-0" />
          ) : (
            <File01Icon className="w-4 h-4 text-zinc-500 shrink-0" />
          )}
          <span
            className={
              isDir
                ? "text-sm font-medium text-zinc-300 truncate"
                : "text-sm text-zinc-400 truncate"
            }
          >
            {node.name}
          </span>
        </div>
        {!isDir && node.size && (
          <span className="text-xs text-zinc-600 shrink-0">{node.size}</span>
        )}
      </div>
      {isDir && open && hasChildren && (
        <div>
          {Object.values(node.children).map((child) => (
            <FileTreeNodeRow key={child.name} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

export function DataCardView(props: z.infer<typeof dataCardSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      <div className="space-y-2">
        {props.fields.map((field) => (
          <div
            key={field.label}
            className="rounded-2xl bg-zinc-900 p-3 flex items-center justify-between gap-4"
          >
            <span className="text-xs text-zinc-500">{field.label}</span>
            <span className="text-sm font-medium text-zinc-200">
              {field.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ResultListView(props: z.infer<typeof resultListSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="space-y-2">
        {props.items.map((item) => (
          <div key={item.title} className="rounded-2xl bg-zinc-900 p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium text-zinc-200">
                {item.title}
              </span>
              {item.badge && (
                <span className="rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs text-zinc-400 shrink-0">
                  {item.badge}
                </span>
              )}
            </div>
            {item.subtitle && (
              <p className="text-xs text-zinc-400 mt-1">{item.subtitle}</p>
            )}
            {item.body && (
              <p className="text-xs text-zinc-400 mt-1">{item.body}</p>
            )}
            {item.url && (
              <div className="flex items-center gap-1 mt-1.5">
                <span className="text-xs text-zinc-600 truncate flex-1">
                  {item.url}
                </span>
                <ArrowRight01Icon className="w-3 h-3 text-zinc-600 shrink-0" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ComparisonTableView(
  props: z.infer<typeof comparisonTableSchema>,
) {
  return (
    <div>
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="rounded-2xl bg-zinc-900 overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800">
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-zinc-500" />
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-zinc-300">
                {props.leftLabel}
              </th>
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-zinc-300">
                {props.rightLabel}
              </th>
            </tr>
          </thead>
          <tbody>
            {props.rows.map((row) => (
              <tr
                key={row.label}
                className={
                  row.highlight
                    ? "bg-[#00bbff]/5"
                    : "hover:bg-zinc-800/40 transition-colors"
                }
              >
                <td className="px-3 py-2 text-xs text-zinc-500">{row.label}</td>
                <td className="px-3 py-2 text-xs text-zinc-300">
                  {row.left.toLowerCase() === "yes" ? (
                    <CheckmarkCircle01Icon className="w-4 h-4 text-emerald-400" />
                  ) : row.left.toLowerCase() === "no" ? (
                    <Cancel01Icon className="w-4 h-4 text-red-400/70" />
                  ) : (
                    row.left
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-zinc-300">
                  {row.right.toLowerCase() === "yes" ? (
                    <CheckmarkCircle01Icon className="w-4 h-4 text-emerald-400" />
                  ) : row.right.toLowerCase() === "no" ? (
                    <Cancel01Icon className="w-4 h-4 text-red-400/70" />
                  ) : (
                    row.right
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function StatusCardView(props: z.infer<typeof statusCardSchema>) {
  const chipColor = STATUS_CHIP_COLOR[props.status] ?? "default";
  const dotColor = STATUS_DOT[props.status] ?? "bg-zinc-500";
  const isPending = props.status === "pending";
  const isInfo = props.status === "info";
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-xl">
      <div className="flex items-center gap-2 mb-2">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          {isPending && (
            <span
              className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-50 ${dotColor}`}
            />
          )}
          <span
            className={`relative inline-flex rounded-full h-2.5 w-2.5 ${dotColor}`}
          />
        </span>
        <p className="text-sm font-medium text-zinc-200 flex-1">
          {props.title}
        </p>
        {isInfo ? (
          <span className="inline-flex items-center rounded-full bg-[#00bbff]/10 px-2 py-0.5 text-xs font-medium text-[#00bbff]">
            {props.status.charAt(0).toUpperCase() + props.status.slice(1)}
          </span>
        ) : (
          <Chip size="sm" variant="flat" color={chipColor}>
            {props.status.charAt(0).toUpperCase() + props.status.slice(1)}
          </Chip>
        )}
      </div>
      {props.message && (
        <p className="text-sm text-zinc-300 mt-1">{props.message}</p>
      )}
      {props.detail && (
        <p className="text-xs text-zinc-500 mt-1">{props.detail}</p>
      )}
    </div>
  );
}

export function ActionCardView(props: z.infer<typeof actionCardSchema>) {
  const handleClick = (value: string) => {
    window.dispatchEvent(
      new CustomEvent("openui:action", {
        detail: { type: "continue_conversation", value },
      }),
    );
  };

  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      <p className="text-sm font-semibold text-zinc-100 mb-1">{props.title}</p>
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      {props.actions && props.actions.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {props.actions.map((action) => (
            <button
              key={action.value}
              type="button"
              onClick={() => handleClick(action.value)}
              className="rounded-full bg-zinc-700/60 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 transition-colors cursor-pointer"
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function TagGroupView(props: z.infer<typeof tagGroupSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {props.tags.map((tag) =>
          tag.color === "primary" ? (
            <span
              key={tag.label}
              className="inline-flex items-center rounded-full bg-[#00bbff]/10 px-2 py-0.5 text-xs font-medium text-[#00bbff]"
            >
              {tag.label}
            </span>
          ) : (
            <Chip
              key={tag.label}
              size="sm"
              variant="flat"
              color={tag.color ?? "default"}
            >
              {tag.label}
            </Chip>
          ),
        )}
      </div>
    </div>
  );
}

export function FileTreeView(props: z.infer<typeof fileTreeSchema>) {
  const tree = buildFileTree(props.items);
  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div>
        {Object.values(tree).map((node) => (
          <FileTreeNodeRow key={node.name} node={node} depth={0} />
        ))}
      </div>
    </div>
  );
}

export function AccordionView(props: z.infer<typeof accordionSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-3 py-0 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 pt-3 pb-2">
          {props.title}
        </p>
      )}
      <HeroAccordion variant="light">
        {props.items.map((item) => (
          <AccordionItem
            key={item.label}
            aria-label={item.label}
            title={
              <span className="text-sm font-medium text-zinc-200">
                {item.label}
              </span>
            }
          >
            <p className="text-xs text-zinc-400 pb-2">{item.content}</p>
          </AccordionItem>
        ))}
      </HeroAccordion>
    </div>
  );
}

export function TabsBlockView(props: z.infer<typeof tabsBlockSchema>) {
  return (
    <Tabs variant="solid" size="sm">
      {props.tabs.map((tab) => (
        <Tab
          key={tab.label}
          title={<span className="text-sm">{tab.label}</span>}
        >
          <div className="rounded-2xl bg-zinc-800/50 p-4">
            <p className="text-sm text-zinc-300 whitespace-pre-wrap">
              {tab.content}
            </p>
          </div>
        </Tab>
      ))}
    </Tabs>
  );
}

export function ProgressListView(props: z.infer<typeof progressListSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="space-y-2">
        {props.items.map((item) => {
          const max = item.max ?? 100;
          const pct = Math.min(100, Math.round((item.value / max) * 100));
          return (
            <div key={item.label} className="rounded-2xl bg-zinc-900 p-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm font-medium text-zinc-200">
                  {item.label}
                </span>
                <span className="text-xs text-zinc-500">{pct}%</span>
              </div>
              <Progress
                value={pct}
                color={item.color ?? "primary"}
                size="sm"
                className="w-full"
                classNames={{
                  indicator:
                    !item.color || item.color === "primary"
                      ? "!bg-[#00bbff]"
                      : undefined,
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SelectableListView(
  props: z.infer<typeof selectableListSchema>,
) {
  const [selected, setSelected] = React.useState<string>("");

  const handleSelect = (value: string) => {
    setSelected(value);
    window.dispatchEvent(
      new CustomEvent("openui:action", {
        detail: { type: "continue_conversation", value },
      }),
    );
  };

  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-sm">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-1">
          {props.title}
        </p>
      )}
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      <RadioGroup
        value={selected}
        onValueChange={handleSelect}
        orientation="vertical"
        classNames={{ wrapper: "space-y-2" }}
      >
        {props.options.map((option) => (
          <Radio
            key={option.value}
            value={option.value}
            classNames={{
              base: [
                "rounded-2xl bg-zinc-900 p-3 m-0 min-w-full cursor-pointer",
                "data-[selected=true]:bg-primary/20!",
              ].join(" "),
              wrapper: "group-data-[selected=true]:border-[#00bbff]",
              label: "text-zinc-200",
              description: "text-zinc-400",
            }}
            description={option.description}
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-zinc-200">
                {option.label}
              </span>
              {option.badge && (
                <span className="rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs text-zinc-400">
                  {option.badge}
                </span>
              )}
            </div>
          </Radio>
        ))}
      </RadioGroup>
    </div>
  );
}

export function AvatarListView(props: z.infer<typeof avatarListSchema>) {
  const hasDetails = props.items.some((item) => item.role || item.description);
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      {hasDetails ? (
        <div className="space-y-2">
          {props.items.map((item) => (
            <div key={item.name} className="flex items-center gap-3">
              <Avatar
                name={item.initials ?? item.name}
                size="sm"
                className="shrink-0"
                style={item.color ? { backgroundColor: item.color } : undefined}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-zinc-200">{item.name}</p>
                {item.role && (
                  <p className="text-xs text-zinc-400">{item.role}</p>
                )}
                {item.description && (
                  <p className="text-xs text-zinc-500 truncate">
                    {item.description}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <AvatarGroup max={7} size="sm">
          {props.items.map((item) => (
            <Avatar
              key={item.name}
              name={item.initials ?? item.name}
              className="shrink-0"
              style={item.color ? { backgroundColor: item.color } : undefined}
            />
          ))}
        </AvatarGroup>
      )}
    </div>
  );
}

export function KbdBlockView(props: z.infer<typeof kbdBlockSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="space-y-2">
        {props.shortcuts.map((shortcut) => (
          <div
            key={shortcut.description}
            className="rounded-2xl bg-zinc-900 p-3 flex items-center justify-between gap-4"
          >
            <span className="text-xs text-zinc-400 flex-1">
              {shortcut.description}
            </span>
            <div className="flex items-center gap-1 shrink-0">
              {shortcut.keys.map((key) => (
                <Kbd key={key}>{key}</Kbd>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

export const dataCardDef = defineComponent({
  name: "DataCard",
  description: "Single record fields as label-value pairs.",
  props: dataCardSchema,
  component: ({ props }) => React.createElement(DataCardView, props),
});

export const resultListDef = defineComponent({
  name: "ResultList",
  description: "List of results with title, subtitle, body, url, badge.",
  props: resultListSchema,
  component: ({ props }) => React.createElement(ResultListView, props),
});

export const comparisonTableDef = defineComponent({
  name: "ComparisonTable",
  description: "A vs B comparison table.",
  props: comparisonTableSchema,
  component: ({ props }) => React.createElement(ComparisonTableView, props),
});

export const statusCardDef = defineComponent({
  name: "StatusCard",
  description: "Operation result card with status indicator.",
  props: statusCardSchema,
  component: ({ props }) => React.createElement(StatusCardView, props),
});

export const actionCardDef = defineComponent({
  name: "ActionCard",
  description: "Next-step suggestions with action buttons.",
  props: actionCardSchema,
  component: ({ props }) => React.createElement(ActionCardView, props),
});

export const tagGroupDef = defineComponent({
  name: "TagGroup",
  description: "Flat set of labeled chips/tags.",
  props: tagGroupSchema,
  component: ({ props }) => React.createElement(TagGroupView, props),
});

export const fileTreeDef = defineComponent({
  name: "FileTree",
  description: "Directory or file listing.",
  props: fileTreeSchema,
  component: ({ props }) => React.createElement(FileTreeView, props),
});

export const accordionDef = defineComponent({
  name: "Accordion",
  description: "Collapsible sections with label and content.",
  props: accordionSchema,
  component: ({ props }) => React.createElement(AccordionView, props),
});

export const tabsBlockDef = defineComponent({
  name: "TabsBlock",
  description: "Tabbed content panels.",
  props: tabsBlockSchema,
  component: ({ props }) => React.createElement(TabsBlockView, props),
});

export const progressListDef = defineComponent({
  name: "ProgressList",
  description: "Labeled progress bars.",
  props: progressListSchema,
  component: ({ props }) => React.createElement(ProgressListView, props),
});

export const selectableListDef = defineComponent({
  name: "SelectableList",
  description: "Selectable options with radio group.",
  props: selectableListSchema,
  component: ({ props }) => React.createElement(SelectableListView, props),
});

export const avatarListDef = defineComponent({
  name: "AvatarList",
  description: "People list with avatars.",
  props: avatarListSchema,
  component: ({ props }) => React.createElement(AvatarListView, props),
});

export const kbdBlockDef = defineComponent({
  name: "KbdBlock",
  description: "Keyboard shortcut reference table.",
  props: kbdBlockSchema,
  component: ({ props }) => React.createElement(KbdBlockView, props),
});
