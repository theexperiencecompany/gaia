import type { Image, Link, Root } from "mdast";
import type { Plugin } from "unified";
import { visit } from "unist-util-visit";
import { resolveArtifactSrc } from "@/features/chat/api/sessionFilesApi";

/**
 * Point links and images at a sandbox artifact path (./artifacts/x, artifacts/x,
 * /workspace/sessions/<id>/artifacts/x) to the file this conversation serves.
 * It runs before the URL hardening, which blocks a bare relative path.
 */
export const remarkArtifactLinks: Plugin<[], Root> = () => {
  return (tree) => {
    visit(tree, ["link", "image"], (node) => {
      const target = node as Link | Image;
      target.url = resolveArtifactSrc(target.url, undefined) ?? target.url;
    });
  };
};
