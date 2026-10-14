import type { FileData } from "@shared/api/generated";

export type { FileData } from "@shared/api/generated";

/** A file as the composer holds it: the API record plus the byte size the browser knows. */
export type AttachedFileData = FileData & { size?: number };
