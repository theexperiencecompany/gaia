/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
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
  readFile: async (path: string): Promise<VFSReadResponse> => ({
    path,
    filename: "",
    content: "",
    content_type: "",
    size_bytes: 0,
  }),

  getInfo: async (path: string): Promise<VFSNodeInfo> => ({
    path,
    name: "",
    node_type: "file",
    size_bytes: 0,
    content_type: "",
    created_at: null,
    updated_at: null,
    metadata: {},
  }),

  listDir: async (
    path: string,
    _recursive = false,
  ): Promise<VFSListResponse> => ({
    path,
    items: [],
    total_count: 0,
  }),
};
