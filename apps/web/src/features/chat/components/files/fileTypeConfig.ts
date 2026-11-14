import {
  AlignRightIcon,
  BookOpen01Icon,
  Chart02Icon,
  CodeIcon,
  ComputerTerminal01Icon,
  Css3Icon,
  CursorTextIcon,
  Database01Icon,
  File01Icon,
  File02Icon,
  FileEditIcon,
  FileSearchIcon,
  GridIcon,
  Html5Icon,
  Image01Icon,
  Image02Icon,
  Image03Icon,
  JavaScriptIcon,
  LayoutTable02Icon,
  Note01Icon,
  PaintBrush01Icon,
  Presentation02Icon,
  PresentationBarChart01Icon,
  PythonIcon,
  SquareRootSquareIcon,
  Typescript01Icon,
  VideoIcon,
  Xml01Icon,
} from "@icons";
import type { ComponentType } from "react";

import { getExtension } from "@/features/chat/utils/fileExtension";

interface FileTypeGlyphProps {
  size?: number;
  color?: string;
  className?: string;
}

type FileTypeGlyph = ComponentType<FileTypeGlyphProps>;

export interface FileTypeStyle {
  from: string;
  to: string;
  Glyph: FileTypeGlyph;
}

/**
 * Every extension the upload allowlist in `apps/api/app/utils/upload_validation.py`
 * accepts (the MIME map below is the exact set it validates), plus the text and
 * code formats GAIA writes as artifacts.
 */
export const FILE_TYPE_STYLES: Readonly<Record<string, FileTypeStyle>> = {
  pdf: { from: "#FF6B5E", to: "#E6202D", Glyph: FileSearchIcon },
  docx: { from: "#4DA6FF", to: "#007AFF", Glyph: FileEditIcon },
  doc: { from: "#5C7CFF", to: "#3250E0", Glyph: File01Icon },
  rtf: { from: "#3ED8F0", to: "#0E93B5", Glyph: AlignRightIcon },
  xlsx: { from: "#52E07A", to: "#1FB653", Glyph: LayoutTable02Icon },
  csv: { from: "#3FE0BF", to: "#12B896", Glyph: GridIcon },
  pptx: { from: "#FFA94D", to: "#FF7A00", Glyph: PresentationBarChart01Icon },
  txt: { from: "#B8C0CC", to: "#7C8694", Glyph: CursorTextIcon },
  md: { from: "#7C8CFF", to: "#5856D6", Glyph: Note01Icon },
  json: { from: "#FFDF5C", to: "#FFC200", Glyph: CodeIcon },
  epub: { from: "#FF9A66", to: "#F4551F", Glyph: BookOpen01Icon },
  odt: { from: "#5FA0F0", to: "#2A6BDC", Glyph: File02Icon },
  ods: { from: "#58E081", to: "#1FAF54", Glyph: Chart02Icon },
  odp: { from: "#FFC15E", to: "#FF7E1A", Glyph: Presentation02Icon },
  png: { from: "#A67CFF", to: "#7D3AF0", Glyph: Image01Icon },
  jpeg: { from: "#4FE0C4", to: "#12B794", Glyph: Image02Icon },
  jpg: { from: "#4FE0C4", to: "#12B794", Glyph: Image02Icon },
  gif: { from: "#FF6B9D", to: "#E8306B", Glyph: VideoIcon },
  webp: { from: "#5FC6FF", to: "#0E9BE6", Glyph: Image03Icon },
  bmp: { from: "#7CA4F0", to: "#3A63D0", Glyph: PaintBrush01Icon },
  svg: { from: "#FFB25E", to: "#F07A1A", Glyph: PaintBrush01Icon },
  html: { from: "#FF8A5C", to: "#E8501E", Glyph: Html5Icon },
  css: { from: "#5FA8FF", to: "#2D6BE0", Glyph: Css3Icon },
  js: { from: "#FFE066", to: "#F2B800", Glyph: JavaScriptIcon },
  jsx: { from: "#6FE3FF", to: "#1AA8D6", Glyph: JavaScriptIcon },
  ts: { from: "#5C9DFF", to: "#2F6FE0", Glyph: Typescript01Icon },
  tsx: { from: "#5C9DFF", to: "#2F6FE0", Glyph: Typescript01Icon },
  py: { from: "#6AA8E8", to: "#3570B8", Glyph: PythonIcon },
  sql: { from: "#B08CFF", to: "#7650E0", Glyph: Database01Icon },
  yaml: { from: "#FF8FB0", to: "#D9466F", Glyph: CodeIcon },
  yml: { from: "#FF8FB0", to: "#D9466F", Glyph: CodeIcon },
  xml: { from: "#FFA35C", to: "#E5701F", Glyph: Xml01Icon },
  sh: { from: "#9AA5B4", to: "#5E6878", Glyph: ComputerTerminal01Icon },
  tex: { from: "#7FD48A", to: "#3C9A4A", Glyph: SquareRootSquareIcon },
  file: { from: "#B8C0CC", to: "#7C8694", Glyph: File01Icon },
};

const MIME_TO_EXTENSION: Readonly<Record<string, string>> = {
  "application/pdf": "pdf",
  "text/plain": "txt",
  "text/markdown": "md",
  "text/csv": "csv",
  "text/rtf": "rtf",
  "application/json": "json",
  "application/epub+zip": "epub",
  "application/vnd.oasis.opendocument.text": "odt",
  "application/vnd.oasis.opendocument.spreadsheet": "ods",
  "application/vnd.oasis.opendocument.presentation": "odp",
  "application/msword": "doc",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
    "docx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation":
    "pptx",
  "image/png": "png",
  "image/jpeg": "jpeg",
  "image/gif": "gif",
  "image/webp": "webp",
  "image/bmp": "bmp",
  "image/svg+xml": "svg",
  "text/html": "html",
};

export function getFileTypeExtension(
  fileType: string,
  fileName: string,
): string {
  const mimeExt = MIME_TO_EXTENSION[fileType];
  if (mimeExt !== undefined) return mimeExt;
  const extension = getExtension(fileName);
  return extension in FILE_TYPE_STYLES ? extension : "file";
}

const getFileExtension = (fileName: string): string => {
  const parts = fileName.split(".");
  return parts.length > 1 ? parts[parts.length - 1] : "";
};

/** Format the file type more clearly, for chip labels. */
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
