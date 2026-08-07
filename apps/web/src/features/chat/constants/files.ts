/** Client-side attachment rules. Size matches the backend /upload cap
 *  (MAX_UPLOAD_BYTES); the type list is a stricter subset of the backend
 *  allowlist (app/utils/upload_validation.py). */
export const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;
export const MAX_FILES = 5;
export const ALLOWED_FILE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
  "image/bmp",
  "application/pdf",
  "text/plain",
  "text/markdown",
  "text/csv",
  "text/rtf",
  "application/json",
  "application/epub+zip",
  "application/vnd.oasis.opendocument.text",
  "application/vnd.oasis.opendocument.spreadsheet",
  "application/vnd.oasis.opendocument.presentation",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
];

/** Pastes longer than this become a .txt attachment instead of inline text,
 *  keeping the composer responsive and routing big content through the file
 *  pipeline (same approach as Claude's paste-to-attachment). */
export const LARGE_PASTE_THRESHOLD_CHARS = 10_000;

export const PASTED_TEXT_FILENAME = "pasted-text.txt";
