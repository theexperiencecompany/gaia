import type { OpenUIArtifactResponse } from "@shared/api/generated";
import { api } from "@/lib/api/typed";

/** One of the user's artifacts; `opened` marks a viewer load, which the server counts. */
export function fetchArtifact(
  artifactId: string,
  opened: boolean,
): Promise<OpenUIArtifactResponse> {
  return api.get("/api/v1/artifacts/{artifact_id}", {
    path: { artifact_id: artifactId },
    query: { opened },
    errorMessage: "Couldn't load this artifact",
  });
}
