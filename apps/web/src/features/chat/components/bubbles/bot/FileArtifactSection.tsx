import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { Download01Icon, File01Icon, LinkSquare02Icon } from "@icons";
import { formatFileSize } from "@shared/utils";
import type React from "react";
import { useCallback, useMemo } from "react";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";
import FileViewerPanel from "@/features/chat/components/artifacts/FileViewerPanel";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { useArtifactText } from "@/features/chat/hooks/useArtifactText";
import { useIsMobile } from "@/hooks/ui/useMobile";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import type { ArtifactData } from "@/types/features/toolDataTypes";

interface FileArtifactSectionProps {
  artifact_data: ArtifactData | ArtifactData[];
}

const EXT_CONTENT_TYPE: Record<string, string> = {
  html: "text/html",
  htm: "text/html",
  md: "text/markdown",
  markdown: "text/markdown",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  svg: "image/svg+xml",
  pdf: "application/pdf",
};

type ArtifactKind = "html" | "markdown" | "image" | "pdf" | "other";

function basename(path: string): string {
  return path.split("/").pop() || path;
}

function resolveContentType(artifact: ArtifactData): string {
  if (artifact.content_type) return artifact.content_type;
  const ext = basename(artifact.path).split(".").pop()?.toLowerCase() || "";
  return EXT_CONTENT_TYPE[ext] || "application/octet-stream";
}

function kindOf(contentType: string): ArtifactKind {
  if (contentType === "text/html") return "html";
  if (contentType === "text/markdown") return "markdown";
  if (contentType.startsWith("image/")) return "image";
  if (contentType === "application/pdf") return "pdf";
  return "other";
}

/** De-dupe by path (last wins) and drop removed artifacts. */
function normalize(input: ArtifactData | ArtifactData[]): ArtifactData[] {
  const list = Array.isArray(input) ? input : [input];
  const byPath = new Map<string, ArtifactData>();
  for (const a of list) {
    if (!a || !a.session_id || !a.path) continue;
    if (a.event === "remove") {
      byPath.delete(a.path);
      continue;
    }
    byPath.set(a.path, a);
  }
  return Array.from(byPath.values());
}

function TextArtifact({
  conversationId,
  path,
  filename,
  kind,
}: {
  conversationId: string;
  path: string;
  filename: string;
  kind: "html" | "markdown";
}) {
  const { text, loading, error } = useArtifactText(conversationId, path);

  if (error) {
    return <p className="p-4 text-xs text-red-400">Failed to load preview.</p>;
  }
  if (loading || text === null) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner size="sm" />
      </div>
    );
  }
  if (kind === "html") {
    return (
      <iframe
        title={filename}
        srcDoc={text}
        sandbox=""
        className="block h-[480px] w-full rounded-2xl border-0 bg-white"
      />
    );
  }
  return (
    <div className="max-h-[480px] overflow-y-auto p-3">
      <MarkdownRenderer content={text} />
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: ArtifactData }) {
  const { setContent, open } = useRightSidebar();
  const isMobile = useIsMobile();

  const conversationId = artifact.session_id;
  const filename = basename(artifact.path);
  const contentType = resolveContentType(artifact);
  const kind = kindOf(contentType);
  const fileUrl = sessionFilesApi.visibleUrl(conversationId, artifact.path);

  const handleOpen = useCallback(() => {
    const useSheet =
      isMobile || (typeof window !== "undefined" && window.innerWidth < 768);
    setContent(
      <FileViewerPanel
        conversationId={conversationId}
        path={artifact.path}
        filename={filename}
        contentType={contentType}
        sizeBytes={artifact.size_bytes}
      />,
    );
    open(useSheet ? "sheet" : "artifact");
  }, [
    artifact.path,
    artifact.size_bytes,
    contentType,
    conversationId,
    filename,
    isMobile,
    open,
    setContent,
  ]);

  const handleDownload = useCallback(() => {
    const link = document.createElement("a");
    link.href = fileUrl;
    link.download = filename;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [fileUrl, filename]);

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <File01Icon className="h-5 w-5 shrink-0 text-primary" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-zinc-100">
              {filename}
            </p>
            <p className="text-xs text-zinc-400">
              {formatFileSize(artifact.size_bytes)}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Chip size="sm" variant="flat" className="text-xs">
            {(filename.split(".").pop() || "file").toUpperCase()}
          </Chip>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={handleOpen}
            aria-label="Open in viewer"
          >
            <LinkSquare02Icon size={16} />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={handleDownload}
            aria-label="Download file"
          >
            <Download01Icon size={16} />
          </Button>
        </div>
      </div>

      {kind === "html" || kind === "markdown" ? (
        <div className="overflow-hidden rounded-2xl bg-zinc-900">
          <TextArtifact
            conversationId={conversationId}
            path={artifact.path}
            filename={filename}
            kind={kind}
          />
        </div>
      ) : null}

      {kind === "image" ? (
        <button
          type="button"
          onClick={handleOpen}
          className="block w-full overflow-hidden rounded-2xl bg-zinc-900"
        >
          {/** biome-ignore lint/performance/noImgElement: agent artifact, not a static asset */}
          <img
            src={fileUrl}
            alt={filename}
            className="max-h-[480px] w-full object-contain"
          />
        </button>
      ) : null}

      {kind === "pdf" ? (
        <iframe
          title={filename}
          src={fileUrl}
          className="block h-[480px] w-full rounded-2xl border-0 bg-white"
        />
      ) : null}
    </div>
  );
}

const FileArtifactSection: React.FC<FileArtifactSectionProps> = ({
  artifact_data,
}) => {
  const artifacts = useMemo(() => normalize(artifact_data), [artifact_data]);

  if (artifacts.length === 0) return null;

  return (
    <div className="mt-3 flex flex-col gap-2">
      {artifacts.map((artifact) => (
        <ArtifactCard key={artifact.path} artifact={artifact} />
      ))}
    </div>
  );
};

export default FileArtifactSection;
