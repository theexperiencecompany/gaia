export type FileTreeNode = {
  name: string;
  type: "file" | "dir" | "item";
  size?: string;
  description?: string;
  children: Record<string, FileTreeNode>;
};

export function buildFileTree(
  items: Array<{
    path: string;
    type?: "file" | "dir" | "item";
    size?: string;
    description?: string;
  }>,
  defaultLeafType: "file" | "item" = "file",
): Record<string, FileTreeNode> {
  const root: Record<string, FileTreeNode> = {};
  for (const item of items) {
    const parts = item.path.replace(/\/$/, "").split("/").filter(Boolean);
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      if (!current[part]) {
        current[part] = {
          name: part,
          type: isLast ? (item.type ?? defaultLeafType) : "dir",
          size: isLast ? item.size : undefined,
          description: isLast ? item.description : undefined,
          children: {},
        };
      }
      current = current[part].children;
    }
  }
  return root;
}
