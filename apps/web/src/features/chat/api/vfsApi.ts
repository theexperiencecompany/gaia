import { apiService } from "@/lib/api";

export interface VFSReadResponse {
  path: string;
  filename: string;
  content: string;
  content_type: string;
  size_bytes: number;
}

export interface VFSNodeInfo {
  path: string;
  name: string;
  node_type: "file" | "folder";
  size_bytes: number;
  content_type: string;
  created_at: string | null;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface VFSListResponse {
  path: string;
  items: VFSNodeInfo[];
  total_count: number;
}

export const vfsApi = {
  readFile: async (path: string): Promise<VFSReadResponse> => {
    return apiService.get<VFSReadResponse>(
      `/vfs/read?path=${encodeURIComponent(path)}`,
      {
        errorMessage: "Failed to load file",
      },
    );
  },

  getInfo: async (path: string): Promise<VFSNodeInfo> => {
    return apiService.get<VFSNodeInfo>(
      `/vfs/info?path=${encodeURIComponent(path)}`,
      {
        errorMessage: "Failed to load file info",
      },
    );
  },

  listDir: async (
    path: string,
    recursive = false,
  ): Promise<VFSListResponse> => {
    return apiService.get<VFSListResponse>(
      `/vfs/list?path=${encodeURIComponent(path)}&recursive=${recursive}`,
      {
        errorMessage: "Failed to list files",
      },
    );
  },
};
