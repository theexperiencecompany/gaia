/**
 * Shared plumbing for the Playwright e2e suite.
 *
 * Everything here rides the dev harness: the API's dev auth bypass means every
 * page load is already authenticated, and the dev router
 * (`/api/v1/dev/*`, only mounted when `ENV=development` + `DEV_AUTH_BYPASS_EMAIL`
 * is set) lets us mint + seed a deterministic user with no WorkOS login.
 *
 * Ports honor `WEB_PORT` / `API_PORT` so per-worktree ports from `.env.worktree`
 * (see `mise run wt:env`) work without edits.
 */

const WEB_PORT = process.env.WEB_PORT ?? "3000";
const API_PORT = process.env.API_PORT ?? "8000";

/**
 * The seeded dev user. Matches the `mise seed` / `mise dev --sim` default.
 *
 * Ports are per-worktree but the Docker infra (Mongo) is shared across all
 * worktrees, and `global-setup` resets → mints → seeds this user. So two
 * worktrees running e2e at once against the SAME `DEV_USER` will clobber each
 * other's data mid-run. Run e2e in one worktree at a time, or give a worktree
 * its own identity by setting `DEV_USER` here AND the matching
 * `DEV_AUTH_BYPASS_EMAIL` on its API (browser page loads carry no `X-Dev-User`
 * header, so the seeded user must equal the server's bypass email).
 */
export const DEV_USER = process.env.DEV_USER ?? "dev@gaia.local";

/** Fail loud on malformed seed counts instead of sending NaN/negatives to the API. */
function seedCount(name: string, fallback: number, min: number): number {
  const raw = process.env[name];
  if (raw === undefined) return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < min) {
    throw new Error(`${name} must be an integer >= ${min}, got "${raw}"`);
  }
  return value;
}

// SEED_TODOS >= 1: the smoke spec asserts on the first seeded todo.
export const SEED_TODOS = seedCount("SEED_TODOS", 5, 1);
export const SEED_CONVERSATIONS = seedCount("SEED_CONVERSATIONS", 2, 0);

export const WEB_BASE_URL = `http://localhost:${WEB_PORT}`;
export const API_BASE_URL = `http://localhost:${API_PORT}/api/v1`;

/**
 * Title of the first seeded todo. The dev seeder creates "Sample todo 1..N"
 * (see `apps/api/app/services/dev_service.py`) — this is the assertion anchor.
 */
export const FIRST_SEEDED_TODO = "Sample todo 1";

/**
 * The scripted chat test only runs against the deterministic sim stack
 * (`mise dev --sim`), where the LLM is replaced by a directive-parsing stub.
 * Set `E2E_SIM=1` to enable it; otherwise it is skipped with a clear reason.
 */
export const SIM_ENABLED = ["1", "true", "yes"].includes(
  (process.env.E2E_SIM ?? "").toLowerCase(),
);

/** Reply text the stub emits for a `[[say:Done!]]` directive. */
export const SCRIPTED_REPLY = "Done!";
/** Chat message whose directives the LLM stub executes verbatim. */
export const SCRIPTED_CHAT_MESSAGE = `[[say:${SCRIPTED_REPLY}]]`;

const NOT_CONFIGURED_HINT =
  "Start the dev stack (`mise dev --sim` or `mise dev`) with " +
  "DEV_AUTH_BYPASS_EMAIL set in apps/api/.env — the dev router only mounts " +
  "when ENV=development and the bypass is configured.";

async function devRequest(
  path: string,
  init: RequestInit & { tolerate404?: boolean } = {},
): Promise<unknown> {
  const { tolerate404, ...requestInit } = init;
  const url = `${API_BASE_URL}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      ...requestInit,
      headers: { "content-type": "application/json", ...requestInit.headers },
    });
  } catch (cause) {
    throw new Error(
      `Cannot reach the dev API at ${url}. Is it running on port ${API_PORT}? ` +
        `${NOT_CONFIGURED_HINT}\nUnderlying error: ${String(cause)}`,
    );
  }

  if (response.status === 404 && !tolerate404) {
    throw new Error(
      `The dev API returned 404 for ${path}. The dev router is not mounted. ` +
        NOT_CONFIGURED_HINT,
    );
  }

  if (response.status === 404 && tolerate404) {
    return null;
  }

  if (!response.ok) {
    const body = await response.text();
    throw new Error(
      `Dev API ${path} failed (${response.status} ${response.statusText}): ${body}`,
    );
  }

  return response.json();
}

/** Remove the dev user + owned data so each run starts from a clean slate. */
export async function resetDevUser(): Promise<void> {
  await devRequest(`/dev/users/${encodeURIComponent(DEV_USER)}`, {
    method: "DELETE",
    tolerate404: true,
  });
}

/** Idempotently mint the dev user via the real signup path. */
export async function mintDevUser(): Promise<void> {
  await devRequest("/dev/users", {
    method: "POST",
    body: JSON.stringify({ email: DEV_USER }),
  });
}

/**
 * Seed deterministic todos + conversations for the dev user. The dev seeder
 * also marks onboarding complete, so specs land on the app shell rather than
 * being bounced to `/onboarding` by the onboarding guard.
 */
export async function seedDevData(): Promise<void> {
  await devRequest("/dev/seed", {
    method: "POST",
    body: JSON.stringify({
      email: DEV_USER,
      todos: SEED_TODOS,
      conversations: SEED_CONVERSATIONS,
    }),
  });
}
