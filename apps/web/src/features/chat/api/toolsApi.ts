export type { ToolInfo } from "@shared/api/generated";

import { api, type RequestOrigin } from "@/lib/api/typed";

export const fetchAvailableTools = ({ background }: RequestOrigin = {}) =>
  api.get("/api/v1/tools", {
    errorMessage: "Failed to fetch available tools",
    silent: true,
    background,
  });
