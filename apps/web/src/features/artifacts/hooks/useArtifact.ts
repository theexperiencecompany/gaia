import { useQuery } from "@tanstack/react-query";
import { fetchArtifact } from "../api/artifactsApi";

/** A stored artifact; a null id waits. A version's program never changes, so it is never refetched. */
export function useArtifact(artifactId: string | null) {
  return useQuery({
    queryKey: ["artifact", artifactId],
    queryFn: () => fetchArtifact(artifactId ?? ""),
    enabled: artifactId !== null,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
