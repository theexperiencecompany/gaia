import { Button } from "@heroui/button";
import { Card, CardBody } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { CodeIcon, Download01Icon, File01Icon } from "@icons";
import { formatFileSize } from "@shared/utils";
import type React from "react";
import { useCallback, useMemo } from "react";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";
import FileViewerPanel from "@/features/chat/components/artifacts/FileViewerPanel";
import { useIsMobile } from "@/hooks/ui/useMobile";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import type { ArtifactData } from "@/types/features/toolDataTypes";

interface FileArtifactSectionProps {
  artifact_data: ArtifactData | ArtifactData[];
}

const FILE_TYPE_CONFIG: Record<
  string,
  {
    label: string;
    color:
      | "primary"
      | "secondary"
      | "success"
      | "warning"
      | "danger"
      | "default";
    icon: "code" | "file";
  }
> = {
  md: { label: "Markdown", color: "secondary", icon: "file" },
  html: { label: "HTML", color: "warning", icon: "code" },
  htm: { label: "HTML", color: "warning", icon: "code" },
  txt: { label: "Text", color: "default", icon: "file" },
  json: { label: "JSON", color: "success", icon: "code" },
  py: { label: "Python", color: "primary", icon: "code" },
  js: { label: "JavaScript", color: "warning", icon: "code" },
  ts: { label: "TypeScript", color: "primary", icon: "code" },
  tsx: { label: "TSX", color: "primary", icon: "code" },
  jsx: { label: "JSX", color: "warning", icon: "code" },
  css: { label: "CSS", color: "secondary", icon: "code" },
  csv: { label: "CSV", color: "success", icon: "file" },
  tex: { label: "LaTeX", color: "danger", icon: "file" },
  sql: { label: "SQL", color: "primary", icon: "code" },
  yaml: { label: "YAML", color: "success", icon: "code" },
  yml: { label: "YAML", color: "success", icon: "code" },
  xml: { label: "XML", color: "warning", icon: "code" },
  sh: { label: "Shell", color: "default", icon: "code" },
};

const EXT_CONTENT_TYPE: Record<string, string> = {
  html: "text/html",
  htm: "text/html",
  md: "text/markdown",
  markdown: "text/markdown",
  tex: "text/x-latex",
  json: "application/json",
  csv: "text/csv",
  txt: "text/plain",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  svg: "image/svg+xml",
  pdf: "application/pdf",
};

function basename(path: string): string {
  return path.split("/").pop() || path;
}

function getFileConfig(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return (
    FILE_TYPE_CONFIG[ext] || {
      label: ext.toUpperCase() || "File",
      color: "default" as const,
      icon: "file" as const,
    }
  );
}

function resolveContentType(artifact: ArtifactData, filename: string): string {
  if (artifact.content_type) return artifact.content_type;
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return EXT_CONTENT_TYPE[ext] || "application/octet-stream";
}

/** De-dupe by path (last wins) and drop removed artifacts — artifacts are
 * pushed repeatedly in real time, so without this the same file would stack
 * duplicate cards. */
function normalize(input: ArtifactData | ArtifactData[]): ArtifactData[] {
  const list = Array.isArray(input) ? input : [input];
  const byPath = new Map<string, ArtifactData>();
  for (const a of list) {
    if (!a?.session_id || !a.path) continue;
    if (a.event === "remove") {
      byPath.delete(a.path);
      continue;
    }
    byPath.set(a.path, a);
  }
  return Array.from(byPath.values());
}

function ArtifactCard({ artifact }: { artifact: ArtifactData }) {
  const { setContent, open } = useRightSidebar();
  const isMobile = useIsMobile();

  const conversationId = artifact.session_id;
  const filename = basename(artifact.path);
  const contentType = resolveContentType(artifact, filename);
  const config = getFileConfig(filename);

  const handleOpen = useCallback(() => {
    const shouldUseSheet =
      isMobile || (typeof window !== "undefined" && window.innerWidth < 768);
    setContent(
      <FileViewerPanel
        conversationId={conversationId}
        path={artifact.path}
        filename={filename}
        contentType={contentType}
        sizeBytes={artifact.size_bytes}
        inlineBody={artifact.body}
      />,
    );
    open(shouldUseSheet ? "sheet" : "artifact");
  }, [
    artifact.body,
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
    link.href = sessionFilesApi.artifactUrl(conversationId, artifact.path);
    link.download = filename;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [artifact.path, conversationId, filename]);

  return (
    <Card
      className="group cursor-pointer border border-zinc-700/80 bg-zinc-900/70 transition-colors hover:border-zinc-500 hover:bg-zinc-900"
      isPressable
      onPress={handleOpen}
    >
      <CardBody className="p-3.5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <div className="flex-shrink-0">
              {config.icon === "code" ? (
                <CodeIcon className="h-5 w-5 text-primary" />
              ) : (
                <File01Icon className="h-5 w-5 text-primary" />
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="mb-1 flex items-center gap-2.5">
                <Chip
                  size="sm"
                  variant="flat"
                  color={config.color}
                  className="text-xs"
                >
                  {config.label}
                </Chip>
                <p className="truncate text-sm font-medium text-white">
                  {filename}
                </p>
              </div>

              <p className="text-xs text-zinc-400/90">
                {formatFileSize(artifact.size_bytes)} · Click to open
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="flat"
              className="font-medium text-zinc-200"
              onPress={handleOpen}
            >
              Open
            </Button>
            <Button
              isIconOnly
              size="sm"
              variant="light"
              className="text-zinc-300 group-hover:text-white"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                handleDownload();
              }}
              aria-label="Download artifact"
            >
              <Download01Icon size={16} />
            </Button>
          </div>
        </div>
      </CardBody>
    </Card>
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
