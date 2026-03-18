import { apiService } from "@/lib/api";

export interface Tool {
  id: string;
  name: string;
  description: string;
  category: string;
  parameters?: ToolParameter[];
  integrationId?: string;
  integrationName?: string;
  tags?: string[];
}

export interface ToolParameter {
  name: string;
  type: string;
  description?: string;
  required?: boolean;
}

export interface ToolsResponse {
  tools: Tool[];
  total: number;
}

export interface ToolCategoriesResponse {
  categories: string[];
}

export interface ToolsByCategoryResponse {
  tools: Tool[];
  category: string;
  total: number;
}

export async function getTools(): Promise<Tool[]> {
  try {
    const response = await apiService.get<ToolsResponse>("/tools");
    return response.tools;
  } catch (error) {
    console.error("Error fetching tools:", error);
    return [];
  }
}

export async function getToolCategories(): Promise<string[]> {
  try {
    const response =
      await apiService.get<ToolCategoriesResponse>("/tools/categories");
    return response.categories;
  } catch (error) {
    console.error("Error fetching tool categories:", error);
    return [];
  }
}

export async function getToolsByCategory(category: string): Promise<Tool[]> {
  try {
    const response = await apiService.get<ToolsByCategoryResponse>(
      `/tools?category=${encodeURIComponent(category)}`,
    );
    return response.tools;
  } catch (error) {
    console.error("Error fetching tools by category:", error);
    return [];
  }
}

export const toolsApi = {
  getTools,
  getToolCategories,
  getToolsByCategory,
};
