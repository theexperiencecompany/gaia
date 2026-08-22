export type FileTreeNode = {
  name: string;
  type: "file" | "dir" | "item";
  size?: string;
  description?: string;
  children: Record<string, FileTreeNode>;
};

/** A flat file entry to place into the tree at its `path`. */
type FileTreeItem = {
  path: string;
  type?: "file" | "dir" | "item";
  size?: string;
  description?: string;
};

function splitPath(path: string): string[] {
  return path.replace(/\/$/, "").split("/").filter(Boolean);
}

// Leaf nodes carry the item's metadata; intermediate nodes are plain dirs.
function createNode(
  name: string,
  item: FileTreeItem,
  isLeaf: boolean,
  defaultLeafType: "file" | "item",
): FileTreeNode {
  return {
    name,
    type: isLeaf ? (item.type ?? defaultLeafType) : "dir",
    size: isLeaf ? item.size : undefined,
    description: isLeaf ? item.description : undefined,
    children: {},
  };
}

// Walks (and creates) the directory chain for one item, attaching its
// metadata to the leaf.
function insertItem(
  root: Record<string, FileTreeNode>,
  item: FileTreeItem,
  defaultLeafType: "file" | "item",
): void {
  const parts = splitPath(item.path);
  let current = root;
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    const isLeaf = i === parts.length - 1;
    if (!current[part]) {
      current[part] = createNode(part, item, isLeaf, defaultLeafType);
    }
    current = current[part].children;
  }
}

export function buildFileTree(
  items: FileTreeItem[],
  defaultLeafType: "file" | "item" = "file",
): Record<string, FileTreeNode> {
  const root: Record<string, FileTreeNode> = {};
  for (const item of items) {
    insertItem(root, item, defaultLeafType);
  }
  return root;
}
