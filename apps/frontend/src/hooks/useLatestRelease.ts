import { useQuery } from "@tanstack/react-query";

interface GitHubRelease {
  id: number;
  name: string;
  tag_name: string;
  html_url: string;
  published_at: string;
  prerelease: boolean;
  draft: boolean;
  body: string;
}

export function useLatestRelease(repo: string) {
  return useQuery<GitHubRelease>({
    queryKey: ["github-release", repo],
    queryFn: async (): Promise<GitHubRelease> => {
      const response = await fetch(
        `https://api.github.com/repos/${repo}/releases/latest`,
      );
      if (!response.ok) {
        throw new Error("Failed to fetch latest release data");
      }
      return response.json();
    },
    staleTime: 1000 * 60 * 60 * 24, // 1 day cache
    gcTime: 1000 * 60 * 60 * 24, // 1 day cache
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}
