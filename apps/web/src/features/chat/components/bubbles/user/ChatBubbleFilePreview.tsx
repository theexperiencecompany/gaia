import Image from "next/image";
import { FileCard } from "@/features/chat/components/files/FileCard";
import { useFilePreview } from "@/features/chat/hooks/useFilePreview";
import type { AttachedFileData } from "@/types/shared/fileTypes";

interface ChatBubbleFilePreviewProps {
  files: AttachedFileData[];
}

function AttachmentCard({ file }: { file: AttachedFileData }) {
  const contentType = file.type ?? "";
  const preview = useFilePreview({
    source: { kind: "url", url: file.url },
    filename: file.filename,
    contentType,
    sizeBytes: file.size,
  });

  return (
    <>
      {preview.panel}
      <FileCard
        name={file.filename}
        mimeType={contentType}
        sizeBytes={file.size}
        onPress={file.url ? preview.open : undefined}
      />
    </>
  );
}

const ChatBubbleFilePreview: React.FC<ChatBubbleFilePreviewProps> = ({
  files,
}) => {
  if (files.length === 0) return null;

  return (
    <div className="mb-2 flex flex-wrap justify-end gap-2">
      {files.map((file) =>
        file.type?.startsWith("image/") ? (
          <div
            key={file.fileId}
            className="max-h-[300px] w-[300px] overflow-hidden rounded-2xl outline outline-1 -outline-offset-1 outline-white/10"
          >
            <Image
              src={file.url}
              alt={file.filename}
              width={1000}
              height={1000}
              className="h-auto w-full object-cover"
            />
          </div>
        ) : (
          <AttachmentCard key={file.fileId} file={file} />
        ),
      )}
    </div>
  );
};

export default ChatBubbleFilePreview;
