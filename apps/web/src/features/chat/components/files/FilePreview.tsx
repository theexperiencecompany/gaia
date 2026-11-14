import { FileCard } from "@/features/chat/components/files/FileCard";
import { useFilePreview } from "@/features/chat/hooks/useFilePreview";

export interface UploadedFilePreview {
  id: string;
  url: string;
  name: string;
  type: string;
  size?: number; // Add size field for readable file-size label
  description?: string; // Add description field from backend
  message?: string; // Add message field from backend
  isUploading?: boolean;
}

interface FilePreviewProps {
  files: UploadedFilePreview[];
  onRemove: (id: string) => void;
}

function ComposerFileCard({
  file,
  onRemove,
}: {
  file: UploadedFilePreview;
  onRemove: (id: string) => void;
}) {
  const preview = useFilePreview({
    source: { kind: "url", url: file.url },
    filename: file.name,
    contentType: file.type,
    sizeBytes: file.size,
  });
  const canOpen = !file.isUploading && file.url !== "";

  return (
    <>
      {preview.panel}
      <FileCard
        name={file.name}
        mimeType={file.type}
        sizeBytes={file.size}
        thumbnailUrl={file.type.startsWith("image/") ? file.url : undefined}
        surface="composer"
        isUploading={file.isUploading}
        onPress={canOpen ? preview.open : undefined}
        onRemove={() => onRemove(file.id)}
      />
    </>
  );
}

const FilePreview: React.FC<FilePreviewProps> = ({ files, onRemove }) => {
  if (files.length === 0) return null;

  return (
    <div className="mb-2 flex w-full flex-col gap-2 rounded-t-xl px-3 py-2">
      <div className="flex w-full flex-wrap gap-2">
        {files.map((file) => (
          <ComposerFileCard key={file.id} file={file} onRemove={onRemove} />
        ))}
      </div>
    </div>
  );
};

export default FilePreview;
