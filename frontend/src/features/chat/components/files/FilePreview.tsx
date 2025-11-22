import { Button } from "@heroui/button";
import Image from "next/image";

import Spinner from "@/components/ui/spinner";
import {
  Cancel01Icon,
  CodeIcon,
  File01Icon,
  Image02Icon,
  MusicNote01Icon,
  Pdf02Icon,
  Video01Icon,
} from "@/icons";

export interface UploadedFilePreview {
  id: string;
  url: string;
  name: string;
  type: string;
  description?: string; // Add description field from backend
  message?: string; // Add message field from backend
  isUploading?: boolean;
  tempId?: string;
}

interface FilePreviewProps {
  files: UploadedFilePreview[];
  onRemove: (id: string) => void;
}

export const getFileIcon = (fileType: string, fileName: string) => {
  const extension = getFileExtension(fileName).toLowerCase();

  // Image files
  if (fileType.startsWith("image/"))
    return <Image02Icon className="h-6 w-6 text-zinc-800" />;

  // Document files
  if (fileType === "application/pdf" || extension === "pdf")
    return <Pdf02Icon className="h-6 w-6 text-zinc-800" />;

  if (
    ["doc", "docx", "odt", "rtf"].includes(extension) ||
    fileType.includes("wordprocessing") ||
    fileType.includes("msword")
  )
    return <File01Icon className="h-6 w-6 text-zinc-800" />;

  // Spreadsheet files
  if (
    ["xls", "xlsx", "csv", "ods"].includes(extension) ||
    fileType.includes("spreadsheet") ||
    fileType.includes("excel")
  )
    return <File01Icon className="h-6 w-6 text-zinc-800" />;

  // Code/text files
  if (["txt", "md"].includes(extension) || fileType === "text/plain")
    return <File01Icon className="h-6 w-6 text-zinc-800" />;

  if (
    [
      "js",
      "ts",
      "jsx",
      "tsx",
      "py",
      "java",
      "c",
      "cpp",
      "html",
      "css",
    ].includes(extension) ||
    fileType.includes("javascript") ||
    fileType.includes("typescript")
  )
    return <CodeIcon className="h-6 w-6 text-yellow-400" />;

  if (["json", "xml", "yaml", "yml"].includes(extension))
    return <File01Icon className="h-6 w-6 text-zinc-400" />;

  // Media files
  if (
    fileType.startsWith("video/") ||
    ["mp4", "avi", "mov", "mkv"].includes(extension)
  )
    return <Video01Icon className="h-6 w-6 text-purple-400" />;

  if (
    fileType.startsWith("audio/") ||
    ["mp3", "wav", "ogg"].includes(extension)
  )
    return <MusicNote01Icon className="h-6 w-6 text-pink-400" />;

  // Archive files
  if (
    ["zip", "rar", "tar", "gz", "7z"].includes(extension) ||
    fileType.includes("archive") ||
    fileType.includes("compressed")
  )
    return <File01Icon className="h-6 w-6 text-amber-400" />;

  // Default fallback
  return <File01Icon className="h-6 w-6 text-zinc-400" />;
};

export const getFileExtension = (fileName: string) => {
  const parts = fileName.split(".");
  return parts.length > 1 ? parts[parts.length - 1] : "";
};

// Format the file type more clearly
export const getFormattedFileType = (fileType: string, fileName: string) => {
  const ext = getFileExtension(fileName).toUpperCase();

  // Handle common document types with cleaner labels
  if (fileType.includes("msword") || fileType.includes("wordprocessing"))
    return "DOC";

  if (fileType.includes("spreadsheet") || fileType.includes("excel"))
    return "SPREADSHEET";

  // Extract meaningful part from MIME type or use extension
  const typePart = fileType.split("/")[1];

  if (!typePart || typePart === "octet-stream") {
    return ext || "FILE";
  }

  // Cleanup and shorten common verbose MIME types
  const cleanType = typePart
    .replace("vnd.openxmlformats-officedocument.", "")
    .replace("vnd.ms-", "")
    .replace("x-", "")
    .replace("document.", "")
    .replace("presentation.", "")
    .replace("application.", "")
    .split(".")[0];

  return cleanType.toUpperCase().substring(0, 8);
};

const FilePreview: React.FC<FilePreviewProps> = ({ files, onRemove }) => {
  if (files.length === 0) return null;

  return (
    <div className="mb-2 flex w-full flex-col gap-2 rounded-t-xl px-3 py-2">
      <div className="flex w-full flex-wrap gap-2">
        {files.map((file) => (
          <div
            key={file.id}
            className={`group relative flex ${
              file.type.startsWith("image/")
                ? "h-14 max-h-14 min-h-14 w-14 max-w-14 min-w-14 justify-center"
                : "max-w-[220px] min-w-[180px] p-2 pr-8"
            } items-center rounded-xl bg-zinc-700 transition-all hover:bg-zinc-900`}
          >
            {file.isUploading && (
              <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-black/30">
                <Spinner />
              </div>
            )}

            <Button
              isIconOnly
              size="sm"
              variant="faded"
              className="absolute top-0 right-0 z-10 h-6 w-6 min-w-0 scale-90 rounded-full opacity-0 transition-all group-hover:opacity-100"
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
                <div className="mr-3 flex h-10 w-10 items-center justify-center rounded-md bg-primary">
                  {getFileIcon(file.type, file.name)}
                </div>
                <div className="flex min-w-0 flex-1 flex-col">
                  <p className="truncate text-sm font-medium text-white">
                    {file.name.length > 18
                      ? `${file.name.substring(0, 15)}...`
                      : file.name}
                  </p>
                  <div className="flex items-center">
                    <span className="text-xs text-zinc-400">
                      {getFormattedFileType(file.type, file.name)}
                    </span>
                  </div>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default FilePreview;
