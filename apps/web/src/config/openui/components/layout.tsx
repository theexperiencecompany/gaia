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
  Copy01Icon,
  File01Icon,
  Folder02Icon,
  Tick01Icon,
} from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";

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
  tabs: z.array(z.object({ label: z.string(), content: z.string() })),
});

export const kbdBlockSchema = z.object({
  shortcuts: z.array(
    z.object({ keys: z.array(z.string()), description: z.string() }),
  ),
  title: z.string().optional(),
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
          {!generic &&
            (isDir ? (
              <Folder02Icon className="w-4 h-4 text-[#00bbff] shrink-0" />
            ) : (
              <File01Icon className="w-4 h-4 text-zinc-500 shrink-0" />
            ))}
          {generic && isDir && (
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 shrink-0 ml-0.5" />
          )}
          {generic && !isDir && (
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-600 shrink-0 ml-0.5" />
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

  const copy = React.useCallback(() => {
    void navigator.clipboard
      .writeText(props.content)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      })
      .catch(() => {});
  }, [props.content]);

  if (inline) {
    return (
      <div className="inline-flex items-center gap-2 rounded-xl bg-zinc-800 px-3 py-1.5 max-w-full">
        <span className="text-xs text-zinc-300 truncate">{props.content}</span>
        <Button
          isIconOnly
          size="sm"
          variant="light"
          onPress={copy}
          aria-label={copied ? "Copied" : "Copy content"}
          className={copied ? "text-emerald-400" : "text-zinc-400"}
        >
          {copied ? (
            <Tick01Icon className="w-3.5 h-3.5" />
          ) : (
            <Copy01Icon className="w-3.5 h-3.5" />
          )}
        </Button>
      </div>
    );
  }

  return (
    <div className="w-full min-w-fit max-w-3xl">
      <div className="rounded-2xl bg-zinc-900 p-3">
        {props.languageHint && (
          <p className="text-xs text-zinc-500 mb-2">{props.languageHint}</p>
        )}
        <div className="flex items-start gap-2">
          <p className="text-sm text-zinc-200 whitespace-pre-wrap break-words flex-1">
            {props.content}
          </p>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={copy}
            aria-label={copied ? "Copied" : "Copy content"}
            className={`shrink-0 ${copied ? "text-emerald-400" : "text-zinc-500"}`}
          >
            {copied ? (
              <Tick01Icon className="w-3.5 h-3.5" />
            ) : (
              <Copy01Icon className="w-3.5 h-3.5" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function FileTreeView(props: z.infer<typeof fileTreeSchema>) {
  const generic = props.variant === "generic";
  const tree = buildFileTree(props.items, generic ? "item" : "file");
  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
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

export function KbdBlockView(props: z.infer<typeof kbdBlockSchema>) {
  return (
    <div className="w-full min-w-fit max-w-lg">
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
  description: "Tabbed content panels.",
  props: tabsBlockSchema,
  component: ({ props }) => React.createElement(TabsBlockView, props),
});

export const kbdBlockDef = defineComponent({
  name: "KbdBlock",
  description: "Keyboard shortcut reference table.",
  props: kbdBlockSchema,
  component: ({ props }) => React.createElement(KbdBlockView, props),
});
