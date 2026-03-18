export enum FileType {
  image = "image",
  pdf = "pdf",
  document = "document",
  spreadsheet = "spreadsheet",
  presentation = "presentation",
  audio = "audio",
  video = "video",
  code = "code",
  archive = "archive",
  other = "other",
}

export interface FileData {
  id?: string;
  name: string;
  url: string;
  size?: number;
  mimeType?: string;
  fileType?: FileType;
}

export interface ImageData {
  url: string;
  width?: number;
  height?: number;
  alt?: string;
  thumbnailUrl?: string;
}

export interface FileUploadResult {
  fileId: string;
  url: string;
  name: string;
  size: number;
  mimeType: string;
}

const IMAGE_MIME_PREFIXES = ["image/"];
const PDF_MIME_TYPES = ["application/pdf"];
const DOCUMENT_MIME_TYPES = [
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "application/rtf",
  "text/rtf",
];
const SPREADSHEET_MIME_TYPES = [
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/csv",
  "application/vnd.oasis.opendocument.spreadsheet",
];
const PRESENTATION_MIME_TYPES = [
  "application/vnd.ms-powerpoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.oasis.opendocument.presentation",
];
const AUDIO_MIME_PREFIXES = ["audio/"];
const VIDEO_MIME_PREFIXES = ["video/"];
const CODE_MIME_TYPES = [
  "text/javascript",
  "application/javascript",
  "text/typescript",
  "text/x-python",
  "text/x-java",
  "text/x-c",
  "text/x-c++",
  "text/html",
  "text/css",
  "application/json",
  "application/xml",
  "text/xml",
  "text/x-rust",
  "text/x-go",
  "text/x-ruby",
  "text/x-php",
  "text/x-shellscript",
];
const ARCHIVE_MIME_TYPES = [
  "application/zip",
  "application/x-zip-compressed",
  "application/x-tar",
  "application/gzip",
  "application/x-gzip",
  "application/x-7z-compressed",
  "application/x-rar-compressed",
  "application/vnd.rar",
];

/**
 * Derive a FileType enum value from a MIME type string.
 * Returns FileType.other for unrecognised MIME types.
 */
export function getFileType(mimeType: string): FileType {
  const normalized = mimeType.toLowerCase().trim();

  if (IMAGE_MIME_PREFIXES.some((p) => normalized.startsWith(p))) {
    return FileType.image;
  }
  if (PDF_MIME_TYPES.includes(normalized)) {
    return FileType.pdf;
  }
  if (DOCUMENT_MIME_TYPES.includes(normalized)) {
    return FileType.document;
  }
  if (SPREADSHEET_MIME_TYPES.includes(normalized)) {
    return FileType.spreadsheet;
  }
  if (PRESENTATION_MIME_TYPES.includes(normalized)) {
    return FileType.presentation;
  }
  if (AUDIO_MIME_PREFIXES.some((p) => normalized.startsWith(p))) {
    return FileType.audio;
  }
  if (VIDEO_MIME_PREFIXES.some((p) => normalized.startsWith(p))) {
    return FileType.video;
  }
  if (CODE_MIME_TYPES.includes(normalized)) {
    return FileType.code;
  }
  if (ARCHIVE_MIME_TYPES.includes(normalized)) {
    return FileType.archive;
  }
  return FileType.other;
}
