import type { Schema } from "@shared/api/generated";
import { api } from "@/lib/api/typed";

export type ToolInfo = Schema<"ToolInfo">;

export type ToolsListResponse = Schema<"ToolsListResponse">;

export const fetchAvailableTools = () =>
  api.get("/api/v1/tools", {
    errorMessage: "Failed to fetch available tools",
    silent: true,
  });
