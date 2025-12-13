// filepath: /home/aryan/Downloads/Projects/GAIA/gaia-frontend/src/components/chat/ChatBubbles/ChatBubbleFilePreview.tsx
import Image from "next/image";

import {
  getFileIcon,
  getFormattedFileType,
} from "@/features/chat/components/files/FilePreview";
import type { FileData } from "@/types/shared";

interface ChatBubbleFilePreviewProps {
  files: FileData[];
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
            className={`group ${
              file?.type?.startsWith("image/")
                ? "flex h-[300px] w-[300px] flex-col items-center justify-center overflow-hidden rounded-xl"
                : "flex w-fit items-center rounded-xl bg-zinc-700 p-3 text-white"
            }`}
          >
            {file?.type?.startsWith("image/") ? (
              <div className="h-full w-full overflow-hidden">
                <Image
                  src={file.url}
                  alt={file.filename}
                  width={1000}
                  height={1000}
                  className="h-full w-full object-cover"
                />
              </div>
            ) : (
              file.type && (
                <div className="flex items-center gap-3">
                  <div className="aspect-square rounded-lg bg-primary p-1">
                    {getFileIcon(file.type, file.filename)}
                  </div>
                  <div>
                    <div className="font-medium">
                      {file.filename.length > 20
                        ? `${file.filename.substring(0, 20)}...`
                        : file.filename}
                    </div>
                    <div className="text-xs text-zinc-300">
                      {getFormattedFileType(file.type, file.filename)}
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
