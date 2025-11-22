import { useQuery } from "@tanstack/react-query";

interface GitHubRepo {
  stargazers_count: number;
  html_url: string;
  name: string;
  full_name: string;
}

export function useGitHubStars(repo: string) {
  return useQuery<GitHubRepo>({
    queryKey: ["github-stars", repo],
    queryFn: async (): Promise<GitHubRepo> => {
      const response = await fetch(`https://api.github.com/repos/${repo}`);
      if (!response.ok) {
        throw new Error("Failed to fetch GitHub repository data");
      }
      return response.json();
    },
    staleTime: 1000 * 60 * 60, // 1 hour cache
    gcTime: 1000 * 60 * 60, // 1 hour cache
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}
