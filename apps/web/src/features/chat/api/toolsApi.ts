import { apiService } from "@/lib/api/service";

export interface ToolInfo {
  name: string;
  category: string; // Integration ID
  display_name: string; // REQUIRED - human-readable name
  icon_url?: string;
  requires_integration: boolean; // false for core platform tools (search, memory, etc.)
}

export interface ToolsListResponse {
  tools: ToolInfo[];
  total_count: number;
  categories: string[];
}

export const fetchAvailableTools = async (): Promise<ToolsListResponse> => {
  return apiService.get<ToolsListResponse>("/tools", {
    errorMessage: "Failed to fetch available tools",
    silent: true,
  });
};
