// Built-in filesystem MCP server. Every path is resolved to its real location
// and must live inside one of the user-approved roots — this containment check
// (after symlink resolution) is the security boundary. Writes are off unless the
// user opted in per this device's manifest.

import type { Dirent } from "node:fs";
import {
  lstat,
  readdir,
  readFile,
  realpath,
  stat,
  writeFile,
} from "node:fs/promises";
import { dirname, extname, join, resolve, sep } from "node:path";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { FilesystemServer } from "./config.types.js";
import { MAX_IMAGE_READ_BYTES, MAX_READ_BYTES } from "./constants.js";

// Mirrors IMAGE_MIME_BY_EXTENSION in apps/api/app/constants/media.py — the
// backend only inlines these formats into model context.
const IMAGE_MIME_BY_EXTENSION: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
};

class PathDeniedError extends Error {}

async function realpathOrNull(path: string): Promise<string | null> {
  try {
    return await realpath(path);
  } catch {
    return null;
  }
}

async function isSymlink(path: string): Promise<boolean> {
  try {
    return (await lstat(path)).isSymbolicLink();
  } catch {
    return false;
  }
}

function isInside(child: string, root: string): boolean {
  return child === root || child.startsWith(root + sep);
}

/**
 * Resolve `requested` and assert it lives under an approved root. `mustExist`
 * false (for writes to new files) resolves the parent instead, so a not-yet-
 * created file is validated by its directory.
 */
async function resolveWithin(
  requested: string,
  roots: string[],
  mustExist: boolean,
): Promise<string> {
  const absolute = resolve(requested);
  const real = await realpathOrNull(absolute);
  if (real) {
    if (roots.some((root) => isInside(real, root))) return real;
    throw new PathDeniedError(
      `Path is outside your approved folders: ${requested}`,
    );
  }
  if (mustExist) {
    throw new PathDeniedError(`No such file or directory: ${requested}`);
  }
  const parentReal = await realpathOrNull(dirname(absolute));
  if (!parentReal || !roots.some((root) => isInside(parentReal, root))) {
    throw new PathDeniedError(
      `Path is outside your approved folders: ${requested}`,
    );
  }
  // `real` was null because the leaf does not resolve — but that includes a
  // dangling symlink (target not created yet). Writing through it would let the
  // OS follow the link and land outside the approved root, so refuse a symlink
  // leaf. Only a genuinely-absent leaf is a safe new-file write.
  if (await isSymlink(absolute)) {
    throw new PathDeniedError(
      `Refusing to write through a symlink: ${requested}`,
    );
  }
  return join(parentReal, absolute.slice(dirname(absolute).length + 1));
}

async function searchTree(
  root: string,
  query: string,
  limit: number,
  results: string[],
): Promise<void> {
  if (results.length >= limit) return;
  let entries: Dirent[];
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (results.length >= limit) return;
    const full = join(root, entry.name);
    if (entry.name.toLowerCase().includes(query.toLowerCase()))
      results.push(full);
    if (entry.isDirectory() && !entry.isSymbolicLink()) {
      await searchTree(full, query, limit, results);
    }
  }
}

export function buildFilesystemServer(config: FilesystemServer): McpServer {
  const server = new McpServer({ name: "gaia-filesystem", version: "0.1.0" });

  // Resolve approved roots once (lazily, on first tool call) so a symlinked
  // root is compared against its real location.
  let rootsPromise: Promise<string[]> | null = null;
  const roots = (): Promise<string[]> => {
    if (!rootsPromise) {
      rootsPromise = Promise.all(config.allow.map(realpathOrNull)).then(
        (resolved) => resolved.filter((r): r is string => r !== null),
      );
    }
    return rootsPromise;
  };

  const denied = (message: string) => ({
    isError: true,
    content: [{ type: "text" as const, text: message }],
  });

  server.registerTool(
    "list_directory",
    {
      description:
        "List the entries (files and folders) in a directory on the user's machine.",
      inputSchema: {
        path: z.string().describe("Absolute path to a directory"),
      },
    },
    async ({ path }) => {
      try {
        const target = await resolveWithin(path, await roots(), true);
        const entries = await readdir(target, { withFileTypes: true });
        const lines = entries.map(
          (e) => `${e.isDirectory() ? "dir " : "file"}  ${e.name}`,
        );
        return {
          content: [{ type: "text", text: lines.join("\n") || "(empty)" }],
        };
      } catch (e) {
        return denied(e instanceof Error ? e.message : String(e));
      }
    },
  );

  server.registerTool(
    "read_file",
    {
      description:
        "Read the contents of a text or image file on the user's machine.",
      inputSchema: { path: z.string().describe("Absolute path to a file") },
    },
    async ({ path }) => {
      try {
        const target = await resolveWithin(path, await roots(), true);
        const info = await stat(target);
        if (!info.isFile()) return denied(`Not a file: ${path}`);

        const imageMime =
          IMAGE_MIME_BY_EXTENSION[extname(target).toLowerCase()];
        if (imageMime) {
          if (info.size > MAX_IMAGE_READ_BYTES) {
            return denied(`Image is too large to read (${info.size} bytes).`);
          }
          const data = await readFile(target);
          // The text block is not optional: the backend streams and persists only
          // the text of a tool result, and a lane that cannot see pixels describes
          // the image from it. Without it the model never learns which file this is.
          return {
            content: [
              {
                type: "text",
                text: `Image file ${target} (${imageMime}, ${info.size} bytes) — shown below.`,
              },
              {
                type: "image",
                data: data.toString("base64"),
                mimeType: imageMime,
              },
            ],
          };
        }

        if (info.size > MAX_READ_BYTES) {
          return denied(`File is too large to read (${info.size} bytes).`);
        }
        const text = await readFile(target, "utf-8");
        return { content: [{ type: "text", text }] };
      } catch (e) {
        return denied(e instanceof Error ? e.message : String(e));
      }
    },
  );

  server.registerTool(
    "search_files",
    {
      description:
        "Recursively find files/folders whose name contains a query, under a directory.",
      inputSchema: {
        path: z
          .string()
          .describe("Absolute path to the directory to search under"),
        query: z.string().describe("Substring to match against names"),
      },
    },
    async ({ path, query }) => {
      try {
        const target = await resolveWithin(path, await roots(), true);
        const results: string[] = [];
        await searchTree(target, query, 200, results);
        return {
          content: [
            { type: "text", text: results.join("\n") || "(no matches)" },
          ],
        };
      } catch (e) {
        return denied(e instanceof Error ? e.message : String(e));
      }
    },
  );

  if (config.allowWrite) {
    server.registerTool(
      "write_file",
      {
        description:
          "Write text to a file on the user's machine (overwrites if it exists).",
        inputSchema: {
          path: z.string().describe("Absolute path to the file to write"),
          content: z.string().describe("Text content to write"),
        },
      },
      async ({ path, content }) => {
        try {
          const target = await resolveWithin(path, await roots(), false);
          await writeFile(target, content, "utf-8");
          return {
            content: [
              {
                type: "text",
                text: `Wrote ${content.length} bytes to ${path}`,
              },
            ],
          };
        } catch (e) {
          return denied(e instanceof Error ? e.message : String(e));
        }
      },
    );
  }

  return server;
}
