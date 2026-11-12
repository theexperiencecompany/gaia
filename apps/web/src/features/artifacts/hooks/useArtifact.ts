import { useQuery } from "@tanstack/react-query";
import { fetchArtifact } from "../api/artifactsApi";

/**
 * A stored artifact; a null id waits. A card's read is cached for good (a version's program
 * never changes); a viewer's read (`opened`) always goes to the server, which counts each open.
 */
export function useArtifact(artifactId: string | null, opened = false) {
  return useQuery({
    queryKey: ["artifact", artifactId, opened],
    queryFn: () => fetchArtifact(artifactId ?? "", opened),
    enabled: artifactId !== null,
    staleTime: opened ? 0 : Number.POSITIVE_INFINITY,
    gcTime: opened ? 0 : undefined,
  });
}
