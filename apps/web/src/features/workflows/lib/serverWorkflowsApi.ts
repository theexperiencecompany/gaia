import { serverApi, serverData, serverDataOrNull } from "@/lib/api/server";

const REQUEST_TIMEOUT_MS = 10_000;
/** The community endpoint pages at most this many workflows per request. */
const COMMUNITY_PAGE_SIZE = 100;

/** The curated explore workflows; empty with no backend configured. */
export async function getExploreWorkflowsServer(limit: number) {
  const client = serverApi();
  if (!client) return [];
  const result = await client.GET("/api/v1/workflows/explore", {
    params: { query: { limit, offset: 0 } },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  return serverData(result).workflows;
}

/** One page of community workflows. */
export async function getCommunityWorkflowsServer(limit: number, offset = 0) {
  const client = serverApi();
  if (!client) return { workflows: [], total: 0 };
  const result = await client.GET("/api/v1/workflows/community", {
    params: { query: { limit, offset } },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  return serverData(result);
}

/** Every published community workflow, walking the paginated endpoint to its total. */
export async function getAllCommunityWorkflowsServer() {
  const all: Awaited<
    ReturnType<typeof getCommunityWorkflowsServer>
  >["workflows"] = [];
  for (let offset = 0; ; offset += COMMUNITY_PAGE_SIZE) {
    const page = await getCommunityWorkflowsServer(COMMUNITY_PAGE_SIZE, offset);
    all.push(...page.workflows);
    if (
      page.workflows.length < COMMUNITY_PAGE_SIZE ||
      all.length >= (page.total ?? 0)
    ) {
      return all;
    }
  }
}

/** One public workflow by slug or id; null when it does not exist. */
export async function getPublicWorkflowServer(workflowRef: string) {
  const client = serverApi();
  if (!client) return null;
  const result = await client.GET("/api/v1/workflows/public/{workflow_ref}", {
    params: { path: { workflow_ref: workflowRef } },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  return serverDataOrNull(result)?.workflow ?? null;
}
