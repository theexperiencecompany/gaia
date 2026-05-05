import {
  AccordionItem,
  Button,
  Accordion as HeroAccordion,
  Kbd,
  Tab,
  Tabs,
} from "@heroui/react";
import {
  ArrowDown01Icon,
  ArrowRight01Icon,
  CheckmarkCircle02Icon,
  Copy01Icon,
  DashedLineCircleIcon,
  File01Icon,
  Folder02Icon,
  WorkflowCircle06Icon,
} from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";
import { cn } from "@/lib/utils";
import { ToolCard } from "../primitives";

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

export const copyableContentSchema = z.object({
  content: z.string(),
  mode: z.enum(["inline", "block"]).optional(),
  languageHint: z.string().optional(),
});

export const fileTreeSchema = z.object({
  items: z.array(
    z.object({
      path: z.string(),
      type: z.enum(["file", "dir", "item"]).optional(),
      size: z.string().optional(),
      description: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
  variant: z.enum(["file", "generic"]).optional(),
});

export const accordionSchema = z.object({
  items: z.array(z.object({ label: z.string(), content: z.string() })),
  title: z.string().optional(),
});

export const tabsBlockSchema = z.object({
  tabs: z.array(z.object({ label: z.string(), content: z.unknown() })),
});

export const kbdRowSchema = z.object({
  keys: z.array(z.string()),
  description: z.string().optional(),
});

// ---------------------------------------------------------------------------
// FileTree helpers
// ---------------------------------------------------------------------------

type FileTreeNode = {
  name: string;
  type: "file" | "dir" | "item";
  size?: string;
  description?: string;
  children: Record<string, FileTreeNode>;
};

function buildFileTree(
  items: Array<{
    path: string;
    type?: "file" | "dir" | "item";
    size?: string;
    description?: string;
  }>,
  defaultLeafType: "file" | "item" = "file",
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
          type: isLast ? (item.type ?? defaultLeafType) : "dir",
          size: isLast ? item.size : undefined,
          description: isLast ? item.description : undefined,
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
  generic,
}: {
  node: FileTreeNode;
  depth: number;
  generic?: boolean;
}) {
  const [open, setOpen] = React.useState(true);
  const isDir = node.type === "dir";
  const hasChildren = Object.keys(node.children).length > 0;

  return (
    <div>
      <div
        className="flex items-center justify-between gap-2 px-2 py-1 rounded-lg transition cursor-pointer select-none group/file [&_span]:hover:text-zinc-100"
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
          {generic ? (
            isDir ? (
              <WorkflowCircle06Icon className="w-3.5 h-3.5 shrink-0 text-zinc-500" />
            ) : (
              <DashedLineCircleIcon className="w-3.5 h-3.5 shrink-0 text-zinc-600" />
            )
          ) : isDir ? (
            <Folder02Icon className="w-4 h-4 shrink-0 text-[#00bbff]" />
          ) : (
            <File01Icon className="w-4 h-4 shrink-0 text-zinc-500" />
          )}
          <div className="min-w-0">
            <span
              className={
                isDir
                  ? "text-sm font-medium text-zinc-300 truncate"
                  : "text-sm text-zinc-400 truncate"
              }
            >
              {node.name}
            </span>
            {generic && node.description && (
              <p className="text-xs text-zinc-600 truncate">
                {node.description}
              </p>
            )}
          </div>
        </div>
        {!isDir && node.size && (
          <span className="text-xs text-zinc-600 shrink-0">{node.size}</span>
        )}
      </div>
      {isDir && open && hasChildren && (
        <div>
          {Object.values(node.children).map((child) => (
            <FileTreeNodeRow
              key={child.name}
              node={child}
              depth={depth + 1}
              generic={generic}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

export function CopyableContentView(
  props: z.infer<typeof copyableContentSchema>,
) {
  const [copied, setCopied] = React.useState(false);
  const inline = props.mode === "inline";
  const timeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(
    () => () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    },
    [],
  );

  const copy = React.useCallback(() => {
    // navigator.clipboard is undefined in non-secure contexts (e.g. http,
    // some webviews). Calling writeText on undefined would throw synchronously
    // before the catch can swallow it.
    if (!navigator.clipboard?.writeText) return;
    void navigator.clipboard
      .writeText(props.content)
      .then(() => {
        setCopied(true);
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        timeoutRef.current = setTimeout(() => setCopied(false), 1800);
      })
      .catch(() => {});
  }, [props.content]);

  if (inline) {
    return (
      <Button
        size="sm"
        variant="flat"
        onPress={copy}
        aria-label={copied ? "Copied" : "Copy content"}
        className="inline-flex items-center gap-1.5 rounded-full bg-zinc-800 hover:bg-zinc-700 transition-colors px-3 py-1.5 min-w-0 h-auto"
      >
        <span className="font-mono text-xs text-zinc-200 truncate">
          {props.content}
        </span>
        {copied ? (
          <CheckmarkCircle02Icon className="w-3.5 h-3.5 shrink-0 text-emerald-400" />
        ) : (
          <Copy01Icon className="w-3 h-3 shrink-0 text-zinc-500" />
        )}
      </Button>
    );
  }

  const isCode =
    props.languageHint !== undefined ||
    props.content.includes("\n") ||
    /^[A-Z_]+=/.test(props.content);

  return (
    <ToolCard size="standard" className="p-3">
      <div className="flex items-start gap-2">
        <pre
          className={cn(
            "flex-1 text-sm leading-relaxed break-words whitespace-pre-wrap",
            isCode ? "font-mono text-zinc-200" : "font-sans text-zinc-300",
          )}
        >
          {props.content}
        </pre>
        <Button
          isIconOnly
          size="sm"
          variant="light"
          onPress={copy}
          aria-label={copied ? "Copied" : "Copy content"}
          className={cn(
            "shrink-0 aspect-square min-w-7 w-7 h-7 p-0",
            copied ? "text-emerald-400" : "text-zinc-500",
          )}
        >
          {copied ? (
            <CheckmarkCircle02Icon className="w-4 h-4" />
          ) : (
            <Copy01Icon className="w-3.5 h-3.5" />
          )}
        </Button>
      </div>
    </ToolCard>
  );
}

export function FileTreeView(props: z.infer<typeof fileTreeSchema>) {
  const generic = props.variant === "generic";
  const tree = buildFileTree(props.items, generic ? "item" : "file");
  return (
    <ToolCard size="standard" title={props.title} className="p-2">
      <div>
        {Object.values(tree).map((node) => (
          <FileTreeNodeRow
            key={node.name}
            node={node}
            depth={0}
            generic={generic}
          />
        ))}
      </div>
    </ToolCard>
  );
}

export function AccordionView(props: z.infer<typeof accordionSchema>) {
  return (
    <div className="w-full max-w-2xl">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100">{props.title}</p>
      )}
      <HeroAccordion variant="light">
        {props.items.map((item) => (
          <AccordionItem
            key={item.label}
            aria-label={item.label}
            classNames={{ trigger: "!cursor-pointer" }}
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

export function TabsBlockView(props: {
  tabs: Array<{ label: string; content: React.ReactNode }>;
}) {
  return (
    <div className="w-full max-w-2xl">
      <Tabs variant="solid" size="sm">
        {props.tabs.map((tab) => (
          <Tab
            key={tab.label}
            title={<span className="text-sm">{tab.label}</span>}
          >
            {typeof tab.content === "string" ? (
              <p className="text-sm text-zinc-300 whitespace-pre-wrap pt-2 max-w-full">
                {tab.content}
              </p>
            ) : (
              <div className="pt-3 max-w-full [&>*]:max-w-full">
                {tab.content}
              </div>
            )}
          </Tab>
        ))}
      </Tabs>
    </div>
  );
}

export function KbdRowView(props: z.infer<typeof kbdRowSchema>) {
  return (
    <div className="flex items-center justify-between gap-4">
      {props.description && (
        <span className="text-xs text-zinc-400 flex-1">
          {props.description}
        </span>
      )}
      <div className="flex items-center gap-1 shrink-0">
        {props.keys.map((key) => (
          <Kbd key={key}>{key}</Kbd>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

export const copyableContentDef = defineComponent({
  name: "CopyableContent",
  description:
    "Copyable non-code text content, supports inline chips and long form blocks.",
  props: copyableContentSchema,
  component: ({ props }) => React.createElement(CopyableContentView, props),
});

export const fileTreeDef = defineComponent({
  name: "FileTree",
  description:
    "File/directory tree (variant='file') or generic collapsible tree (variant='generic').",
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
  description: "Tabbed content panels — each tab can contain any OpenUI node.",
  props: tabsBlockSchema,
  component: ({ props, renderNode }) => (
    <TabsBlockView
      tabs={props.tabs.map((tab) => ({
        label: tab.label,
        content:
          typeof tab.content === "string"
            ? tab.content
            : renderNode(tab.content),
      }))}
    />
  ),
});

export const kbdRowDef = defineComponent({
  name: "KbdRow",
  description:
    "A single keyboard shortcut row — keys + description. Compose inside a Card for a shortcut table.",
  props: kbdRowSchema,
  component: ({ props }) => React.createElement(KbdRowView, props),
});
