import {
  ArrowDown01Icon,
  ArrowRight01Icon,
  DashedLineCircleIcon,
  File01Icon,
  Folder02Icon,
  WorkflowCircle06Icon,
} from "@icons";
import React from "react";
import type { FileTreeNode } from "./fileTreeUtils";

// Chevron shown on expandable directories; non-directories get a spacer to
// keep rows aligned.
function ToggleIndicator({ expanded }: { expanded: boolean }) {
  return expanded ? (
    <ArrowDown01Icon className="w-3 h-3 text-zinc-500 shrink-0" />
  ) : (
    <ArrowRight01Icon className="w-3 h-3 text-zinc-500 shrink-0" />
  );
}

// Icon for the node type: generic trees use workflow markers, real file trees
// use folder/file icons.
function NodeTypeIcon({
  node,
  generic,
}: {
  node: FileTreeNode;
  generic?: boolean;
}) {
  if (generic) {
    return node.type === "dir" ? (
      <WorkflowCircle06Icon className="w-3.5 h-3.5 shrink-0 text-zinc-500" />
    ) : (
      <DashedLineCircleIcon className="w-3.5 h-3.5 shrink-0 text-zinc-600" />
    );
  }
  return node.type === "dir" ? (
    <Folder02Icon className="w-4 h-4 shrink-0 text-[#00bbff]" />
  ) : (
    <File01Icon className="w-4 h-4 shrink-0 text-zinc-500" />
  );
}

function getNodeNameClassName(isDir: boolean): string {
  return isDir
    ? "text-sm font-medium text-zinc-300 truncate"
    : "text-sm text-zinc-400 truncate";
}

// Enter / Space activates an expandable row like a click, matching its
// role="button" semantics.
function handleRowKeyDown(event: React.KeyboardEvent, toggle: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    toggle();
  }
}

export function FileTreeNodeRow({
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
  const isExpandable = isDir && hasChildren;
  const toggle = () => setOpen((o) => !o);

  return (
    <div>
      <div
        className="flex items-center justify-between gap-2 px-2 py-1 rounded-lg transition cursor-pointer select-none group/file [&_span]:hover:text-zinc-100"
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        role={isExpandable ? "button" : undefined}
        tabIndex={isExpandable ? 0 : undefined}
        onClick={isExpandable ? toggle : undefined}
        onKeyDown={
          isExpandable ? (event) => handleRowKeyDown(event, toggle) : undefined
        }
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {isExpandable ? (
            <ToggleIndicator expanded={open} />
          ) : (
            <span className="w-3 h-3 shrink-0" />
          )}
          <NodeTypeIcon node={node} generic={generic} />
          <div className="min-w-0">
            <span className={getNodeNameClassName(isDir)}>{node.name}</span>
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
      {isExpandable && open && (
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
