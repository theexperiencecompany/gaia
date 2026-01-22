import { apiService } from "@/lib/api";

export interface ToolInfo {
  name: string;
  category: string; // Integration ID
  display_name: string; // REQUIRED - human-readable name
  icon_url?: string;
}

export interface ToolsListResponse {
  tools: ToolInfo[];
  total_count: number;
  categories: string[];
}

export interface ToolsCategoryResponse {
  [category: string]: number;
}

export const fetchAvailableTools = async (): Promise<ToolsListResponse> => {
  return apiService.get<ToolsListResponse>("/tools", {
    errorMessage: "Failed to fetch available tools",
    silent: true,
  });
};
