import type { Schema } from "@shared/api/generated";
export type FileData = Schema<"FileData">;

/** A file as the composer holds it: the API record plus the byte size the browser knows. */
export type AttachedFileData = FileData & { size?: number };
