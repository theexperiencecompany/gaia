import { DEV_USER, mintDevUser, resetDevUser, seedDevData } from "./harness";

/**
 * Bootstraps a deterministic authenticated environment before any spec runs.
 *
 * Reset → mint → seed, all through the real dev endpoints (no raw DB writes, no
 * auth fixtures). Seeding marks onboarding complete, so specs land on the app
 * shell instead of the onboarding flow. Fails fast with an actionable message
 * if the stack isn't reachable or the dev router isn't mounted.
 */
async function globalSetup(): Promise<void> {
  await resetDevUser();
  await mintDevUser();
  await seedDevData();

  console.info(`[e2e] seeded dev user ${DEV_USER} (onboarding complete)`);
}

export default globalSetup;
