import { Handle, Position } from "@xyflow/react";
import React from "react";

import type { NodeData } from "@/types/features/goalTypes";

interface CustomNodeProps {
  data: NodeData;
  currentlySelectedNodeId: string | null;
  setCurrentlySelectedNodeId: React.Dispatch<
    React.SetStateAction<string | null>
  >;
  setOpenSidebar: React.Dispatch<React.SetStateAction<boolean>>;
}

const CustomNode: React.FC<CustomNodeProps> = React.memo(
  ({
    data,
    currentlySelectedNodeId,
    setCurrentlySelectedNodeId,
    setOpenSidebar,
  }) => {
    return (
      <>
        <Handle position={Position.Top} type="target" />
        <div
          className={`${
            currentlySelectedNodeId === data.id
              ? "shadow-lg outline-[#00bbff]!"
              : "outline-zinc-700"
          } ${
            data.isComplete
              ? "bg-[#00bbff73] line-through outline-[#00bbff30]"
              : "bg-zinc-800"
          } flex max-w-[250px] min-w-[250px] flex-row items-center justify-center gap-1 rounded-lg p-4 text-center text-white outline outline-[3px] transition-all`}
          onClick={() => {
            setCurrentlySelectedNodeId(data.id);
            setOpenSidebar(true);
          }}
        >
          {data.label}
        </div>
        <Handle position={Position.Bottom} type="source" />
      </>
    );
  },
);

CustomNode.displayName = "CustomNode";

export default CustomNode;
