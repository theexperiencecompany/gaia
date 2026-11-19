import type { OpenUIArtifactResponse } from "@shared/api/generated";
import { API_BASE } from "@/lib/api/baseUrl";
import { api } from "@/lib/api/typed";

/** One of the user's artifacts, program included. */
export function fetchArtifact(
  artifactId: string,
): Promise<OpenUIArtifactResponse> {
  return api.get("/api/v1/artifacts/{artifact_id}", {
    path: { artifact_id: artifactId },
    errorMessage: "Couldn't load this artifact",
  });
}

/** Browser URL of the owner's PDF export; it needs no public link. */
export function artifactPdfDownloadUrl(artifactId: string): string {
  return `${API_BASE}/artifacts/${encodeURIComponent(artifactId)}/pdf`;
}
