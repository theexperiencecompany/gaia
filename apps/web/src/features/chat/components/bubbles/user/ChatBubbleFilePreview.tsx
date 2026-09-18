import { formatFileSize } from "@shared/utils";
import Image from "next/image";
import { FileTypeIcon } from "@/features/chat/components/files/FileTypeIcon";
import {
  getFileTypeExtension,
  getFormattedFileType,
} from "@/features/chat/components/files/fileTypeConfig";
import type { AttachedFileData } from "@/types/shared/fileTypes";

interface ChatBubbleFilePreviewProps {
  files: AttachedFileData[];
}

const ChatBubbleFilePreview: React.FC<ChatBubbleFilePreviewProps> = ({
  files,
}) => {
  if (files.length === 0) return null;

  return (
    <div className="mb-2 flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {files.map((file) => (
          <div
            key={file.fileId}
            className={`group/filetype group ${file?.type?.startsWith("image/") ? "flex max-h-[320px] w-fit max-w-full flex-col items-center justify-center overflow-hidden rounded-xl" : "flex w-fit items-center rounded-xl bg-zinc-700 p-3 text-white"}`}
          >
            {file?.type?.startsWith("image/") ? (
              <div className="flex max-h-[320px] w-fit max-w-full items-center justify-center overflow-hidden">
                <Image
                  src={file.url}
                  alt={file.filename}
                  width={1000}
                  height={1000}
                  className="h-auto max-h-[320px] w-auto max-w-full rounded-xl object-contain"
                />
              </div>
            ) : (
              file.type && (
                <div className="flex items-center gap-3">
                  <FileTypeIcon
                    extension={getFileTypeExtension(file.type, file.filename)}
                    size={36}
                  />
                  <div>
                    <div className="text-sm font-medium">
                      {file.filename.length > 20
                        ? `${file.filename.substring(0, 20)}...`
                        : file.filename}
                    </div>
                    <div className="text-xs text-zinc-300">
                      {file.size !== undefined
                        ? formatFileSize(file.size)
                        : getFormattedFileType(file.type, file.filename)}
                    </div>
                  </div>
                </div>
              )
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default ChatBubbleFilePreview;
