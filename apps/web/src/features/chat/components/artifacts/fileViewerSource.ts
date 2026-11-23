import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";

/** Where the viewer reads a file from: GAIA's session workspace, or a plain URL (an upload). */
export type FileViewerSource =
  | {
      kind: "artifact";
      conversationId: string;
      path: string;
      /** Small textual artifacts carry their body on the event. */
      inlineBody?: string;
    }
  | { kind: "url"; url: string };

/** The URL the browser loads the file's bytes from (images, PDFs, downloads). */
export function fileViewerSourceUrl(source: FileViewerSource): string {
  return source.kind === "artifact"
    ? sessionFilesApi.artifactUrl(source.conversationId, source.path)
    : source.url;
}
