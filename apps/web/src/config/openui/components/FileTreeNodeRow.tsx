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

  return (
    <div>
      <div
        className="flex items-center justify-between gap-2 px-2 py-1 rounded-lg transition cursor-pointer select-none group/file [&_span]:hover:text-zinc-100"
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        role={isDir && hasChildren ? "button" : undefined}
        tabIndex={isDir && hasChildren ? 0 : undefined}
        onClick={isDir && hasChildren ? () => setOpen((o) => !o) : undefined}
        onKeyDown={
          isDir && hasChildren
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setOpen((o) => !o);
                }
              }
            : undefined
        }
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
