import { Button } from "@heroui/button";
import { Card, CardBody } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { CodeIcon, Download01Icon, File01Icon } from "@icons";
import type React from "react";
import { useCallback } from "react";
import { vfsApi } from "@/features/chat/api/vfsApi";
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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function ArtifactCard({ artifact }: { artifact: ArtifactData }) {
  const { setContent, open } = useRightSidebar();
  const isMobile = useIsMobile();
  const config = getFileConfig(artifact.filename);

  const handleOpen = useCallback(() => {
    const shouldUseSheet =
      isMobile || (typeof window !== "undefined" && window.innerWidth < 768);

    setContent(
      <FileViewerPanel
        path={artifact.path}
        filename={artifact.filename}
        contentType={artifact.content_type}
      />,
    );
    open(shouldUseSheet ? "sheet" : "artifact");
  }, [artifact, isMobile, open, setContent]);

  const handleDownload = useCallback(async () => {
    try {
      const response = await vfsApi.readFile(artifact.path);
      const blob = new Blob([response.content], {
        type: artifact.content_type,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = artifact.filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      // Silent fail - download unavailable
    }
  }, [artifact]);

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
                  {artifact.filename}
                </p>
              </div>

              <p className="text-xs text-zinc-400/90">
                {formatSize(artifact.size_bytes)} · Click to open
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
                void handleDownload();
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
  const artifacts = Array.isArray(artifact_data)
    ? artifact_data
    : [artifact_data];

  return (
    <div className="mt-3 flex flex-col gap-2">
      {artifacts.map((artifact, index) => (
        <ArtifactCard key={`${artifact.path}-${index}`} artifact={artifact} />
      ))}
    </div>
  );
};

export default FileArtifactSection;
