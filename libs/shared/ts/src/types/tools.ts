export type ToolCategory =
  | "web"
  | "email"
  | "calendar"
  | "todos"
  | "files"
  | "code"
  | "search"
  | "communication"
  | "productivity"
  | string;

export interface Tool {
  id: string;
  name: string;
  description: string;
  category: ToolCategory;
  enabled?: boolean;
  icon?: string;
}

export interface ToolsListResponse {
  tools: Tool[];
  total: number;
}

export interface ToolsByCategoryResponse {
  category: ToolCategory;
  tools: Tool[];
}
