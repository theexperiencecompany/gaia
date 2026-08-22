import type { z } from "zod";
import { ToolCard } from "../primitives/ToolCard";
import type { fileTreeSchema } from "../promptSpecs";
import { FileTreeNodeRow } from "./FileTreeNodeRow";
import { buildFileTree } from "./fileTreeUtils";

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
