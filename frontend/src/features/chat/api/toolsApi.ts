import { apiService } from "@/lib/api";

export interface ToolInfo {
  name: string;
  category: string;
  required_integration?: string;
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
    silent: true, // Don't show error toast since this is used in background
  });
};
