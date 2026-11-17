import { useQuery } from "@tanstack/react-query";
import { fetchArtifact } from "../api/artifactsApi";

/** A stored artifact; a null id waits. An artifact is written once, so it is never refetched. */
export function useArtifact(artifactId: string | null) {
  return useQuery({
    queryKey: ["artifact", artifactId],
    queryFn: () => fetchArtifact(artifactId ?? ""),
    enabled: artifactId !== null,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
