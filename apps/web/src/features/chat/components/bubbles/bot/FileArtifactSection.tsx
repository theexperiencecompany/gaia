import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { Download01Icon } from "@icons";
import type React from "react";
import { useCallback, useMemo } from "react";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";
import { FileCard } from "@/features/chat/components/files/FileCard";
import { useFilePreview } from "@/features/chat/hooks/useFilePreview";
import { getExtension } from "@/features/chat/utils/fileExtension";
import { ShareLinkControls } from "@/features/short-links/components/ShareLinkControls";
import { sessionArtifactTargetId } from "@/features/short-links/utils/sessionArtifactTargetId";
import { useConversationArtifacts } from "@/stores/chatStore";
import type { ArtifactData } from "@/types/features/toolDataTypes";

interface FileArtifactSectionProps {
  artifact_data: ArtifactData | ArtifactData[];
}

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

function resolveContentType(artifact: ArtifactData, filename: string): string {
  if (artifact.content_type) return artifact.content_type;
  const ext = getExtension(filename);
  return EXT_CONTENT_TYPE[ext] || "application/octet-stream";
}

/** De-dupe by path (last wins), drop removed artifacts, and resolve each path
 * reference to its full data from the conversation registry. Entries are path
 * references; full data (size, inline body) lives in `artifactMap`. The `?? a`
 * fallback keeps legacy full-data messages rendering before any registry sync. */
function normalize(
  input: ArtifactData | ArtifactData[],
  artifactMap: Record<string, ArtifactData>,
): ArtifactData[] {
  const list = Array.isArray(input) ? input : [input];
  const byPath = new Map<string, ArtifactData>();
  for (const a of list) {
    if (!a?.session_id || !a.path) continue;
    if (a.event === "remove") {
      byPath.delete(a.path);
      continue;
    }
    byPath.set(a.path, artifactMap[a.path] ?? a);
  }
  return Array.from(byPath.values());
}

function ArtifactCard({ artifact }: { artifact: ArtifactData }) {
  const conversationId = artifact.session_id;
  const filename = basename(artifact.path);
  const contentType = resolveContentType(artifact, filename);
  const preview = useFilePreview({
    source: {
      kind: "artifact",
      conversationId,
      path: artifact.path,
      inlineBody: artifact.body,
    },
    filename,
    contentType,
    sizeBytes: artifact.size_bytes,
  });

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
    <>
      {preview.panel}
      <FileCard
        name={filename}
        mimeType={contentType}
        sizeBytes={artifact.size_bytes}
        onPress={preview.open}
        actions={
          <>
            <ShareLinkControls
              targetType="session_artifact"
              targetId={sessionArtifactTargetId(conversationId, artifact.path)}
            />
            <Tooltip content="Download" placement="bottom">
              <Button
                isIconOnly
                size="sm"
                variant="light"
                aria-label="Download"
                onPress={handleDownload}
              >
                <Download01Icon size={16} />
              </Button>
            </Tooltip>
          </>
        }
      />
    </>
  );
}

const FileArtifactSection: React.FC<FileArtifactSectionProps> = ({
  artifact_data,
}) => {
  const conversationId = useMemo(() => {
    const list = Array.isArray(artifact_data) ? artifact_data : [artifact_data];
    return list.find((a) => a?.session_id)?.session_id ?? "";
  }, [artifact_data]);
  const artifactMap = useConversationArtifacts(conversationId);
  const artifacts = useMemo(
    () => normalize(artifact_data, artifactMap),
    [artifact_data, artifactMap],
  );

  if (artifacts.length === 0) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {artifacts.map((artifact) => (
        <ArtifactCard key={artifact.path} artifact={artifact} />
      ))}
    </div>
  );
};

export default FileArtifactSection;
