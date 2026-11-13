export type { ToolInfo } from "@shared/api/generated";

import { api } from "@/lib/api/typed";

export const fetchAvailableTools = () =>
  api.get("/api/v1/tools", {
    errorMessage: "Failed to fetch available tools",
    silent: true,
  });
