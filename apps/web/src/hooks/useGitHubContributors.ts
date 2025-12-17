import { useQuery } from "@tanstack/react-query";

interface GitHubContributor {
  login: string;
  id: number;
  avatar_url: string;
  html_url: string;
  contributions: number;
  type?: string;
}

interface ContributorsData {
  contributors: GitHubContributor[];
  totalCount: number;
}

async function fetchContributorsCount(repo: string): Promise<number> {
  const response = await fetch(
    `https://api.github.com/repos/${repo}/contributors?per_page=1&anon=true`,
  );

  if (!response.ok) {
    throw new Error("Failed to fetch contributors count");
  }

  const linkHeader = response.headers.get("link");

  if (linkHeader?.includes('rel="last"')) {
    const match = linkHeader.match(/&page=(\d+)>; rel="last"/);
    return match ? parseInt(match[1], 10) : 1;
  } else {
    const data = await response.json();
    return data.length;
  }
}

async function fetchTopContributors(
  repo: string,
): Promise<GitHubContributor[]> {
  const response = await fetch(
    `https://api.github.com/repos/${repo}/contributors?per_page=30&page=1`,
  );

  if (!response.ok) {
    throw new Error("Failed to fetch contributors");
  }

  const data: GitHubContributor[] = await response.json();

  // Filter out bots and automated accounts
  const filteredContributors = data.filter((contributor) => {
    const login = contributor.login.toLowerCase();
    return (
      !login.includes("bot") &&
      !login.includes("dependabot") &&
      !login.includes("actions-user") &&
      !login.includes("github-actions") &&
      contributor.type !== "Bot"
    );
  });

  // Return top 10 real contributors
  return filteredContributors.slice(0, 10);
}

export function useGitHubContributors(repo: string) {
  return useQuery<ContributorsData>({
    queryKey: ["github-contributors", repo],
    queryFn: async (): Promise<ContributorsData> => {
      const [contributors, totalCount] = await Promise.all([
        fetchTopContributors(repo),
        fetchContributorsCount(repo),
      ]);

      return {
        contributors,
        totalCount,
      };
    },
    staleTime: 1000 * 60 * 60, // 1 hour cache
    gcTime: 1000 * 60 * 60 * 2, // 2 hours cache
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}
