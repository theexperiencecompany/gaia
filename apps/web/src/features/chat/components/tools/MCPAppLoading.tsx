import { Skeleton } from "@heroui/react";
import { MCP_APP_INITIAL_HEIGHT_PX } from "@/features/chat/constants/mcpApp";

/** The MCP app card's footprint while its renderer chunk loads. */
export function MCPAppLoading() {
  return (
    <div
      role="status"
      aria-label="Loading app"
      className="my-2 w-full max-w-2xl rounded-2xl bg-zinc-800 p-4"
      style={{ height: MCP_APP_INITIAL_HEIGHT_PX }}
    >
      <Skeleton className="h-full w-full rounded-2xl" />
    </div>
  );
}
