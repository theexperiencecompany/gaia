import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import { Cancel01Icon } from "@icons";
import { formatFileSize } from "@shared/utils";
import Image from "next/image";
import { useState } from "react";
import { FileTypeIcon } from "@/features/chat/components/files/FileTypeIcon";
import {
  getFileTypeExtension,
  getFormattedFileType,
} from "@/features/chat/components/files/fileTypeConfig";

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

const FileChip: React.FC<{
  file: UploadedFilePreview;
  onRemove: (id: string) => void;
}> = ({ file, onRemove }) => {
  const [isHovered, setIsHovered] = useState(false);
  const isTruncated = file.name.length > 18;

  return (
    <div
      className={`group/filetype group relative flex ${file.type.startsWith("image/") ? "h-14 max-h-14 min-h-14 w-14 max-w-14 min-w-14 justify-center" : "max-w-[220px] min-w-[180px] p-2 pr-8"} items-center rounded-xl bg-zinc-700 transition-colors hover:bg-zinc-900`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {file.isUploading && (
        <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-black/30">
          <Spinner size="sm" />
        </div>
      )}

      <Button
        isIconOnly
        size="sm"
        variant="faded"
        isDisabled={file.isUploading}
        className="absolute top-0 right-0 z-10 h-6 w-6 min-w-0 scale-90 rounded-full opacity-0 transition-opacity group-hover:opacity-100"
        onPress={() => onRemove(file.id)}
      >
        <Cancel01Icon size={14} />
      </Button>

      {file.type.startsWith("image/") ? (
        <div className="h-12 w-12 overflow-hidden rounded-md">
          <Image
            src={file.url}
            alt={file.name}
            width={40}
            height={40}
            className="h-full w-full object-cover"
          />
        </div>
      ) : (
        <>
          <div className="mr-2.5 flex shrink-0 items-center">
            <FileTypeIcon
              extension={getFileTypeExtension(file.type, file.name)}
              size={36}
              isHovered={isHovered}
            />
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            {isTruncated ? (
              <Tooltip
                content={file.name}
                placement="top-start"
                showArrow
                isOpen={isHovered}
              >
                <p className="truncate text-sm font-medium text-white">
                  {file.name.substring(0, 15)}...
                </p>
              </Tooltip>
            ) : (
              <p className="truncate text-sm font-medium text-white">
                {file.name}
              </p>
            )}
            <div className="flex items-center">
              <span className="text-xs text-zinc-400">
                {file.size !== undefined
                  ? formatFileSize(file.size)
                  : getFormattedFileType(file.type, file.name)}
              </span>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

const FilePreview: React.FC<FilePreviewProps> = ({ files, onRemove }) => {
  if (files.length === 0) return null;

  return (
    <div className="mb-2 flex w-full flex-col gap-2 rounded-t-xl px-3 py-2">
      <div className="flex w-full flex-wrap gap-2">
        {files.map((file) => (
          <FileChip key={file.id} file={file} onRemove={onRemove} />
        ))}
      </div>
    </div>
  );
};

export default FilePreview;
