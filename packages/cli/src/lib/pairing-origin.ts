/**
 * What `gaia bridge login` should do about the self-host install recorded on
 * this machine. An install is only a pairing target while GAIA answers there:
 * its web port can be held by any other program (a dev web app answers
 * `/api/v1/*` with its own 404), and pairing against that reports a bare 404
 * from the wrong server.
 * @module lib/pairing-origin
 */

import { DEFAULT_API_URL } from "@gaia/shared/bridge-core/constants";
import { readConfig } from "./config.js";
import { localApiUrl, localOrigin } from "./endpoints.js";
import { readDockerComposePortOverrides } from "./env-writer.js";
import { type GaiaProbe, probeGaia } from "./gaia-health.js";
import { homeRelative } from "./paths.js";

/** The two answers that mean "don't pair here": nothing, or not GAIA. */
type NotServingHealth = Exclude<GaiaProbe, { kind: "gaia" }>;

export type SelfhostPairing =
  | { kind: "serving"; origin: string }
  | {
      kind: "not-serving";
      /** The install as a person reads it (~/gaia). */
      install: string;
      origin: string;
      /** Whether an earlier `gaia up` finished setting this install up. */
      finishedSetup: boolean;
      health: NotServingHealth;
    };

export type NotServing = Extract<SelfhostPairing, { kind: "not-serving" }>;

const PAIR_WITH_CLOUD = `pair with GAIA Cloud instead: gaia bridge login --api ${DEFAULT_API_URL}`;

/**
 * Whether this install is a pairing target: the origin when GAIA answers, else
 * what answered instead. The decision to pair somewhere else stays with the
 * caller.
 */
export async function selfhostPairing(
  repoPath: string,
): Promise<SelfhostPairing> {
  const overrides = readDockerComposePortOverrides(repoPath);
  const health = await probeGaia(localApiUrl("selfhost", overrides));
  if (health.kind === "gaia") {
    return { kind: "serving", origin: localOrigin("selfhost", overrides) };
  }
  return {
    kind: "not-serving",
    install: homeRelative(repoPath),
    origin: localOrigin("selfhost", overrides),
    finishedSetup: readConfig()?.setupComplete === true,
    health,
  };
}

/** One line asking whether to pair with GAIA Cloud instead. */
export function notServingPrompt(pairing: NotServing): string {
  const unfinished = pairing.finishedSetup
    ? ""
    : " (it never finished setting up)";
  return `GAIA's install at ${pairing.install} isn't answering at ${pairing.origin}${unfinished}. Pair with GAIA Cloud instead?`;
}

/** What the install answered, and the ways forward. */
export function notServingHelp(pairing: NotServing): string {
  if (pairing.health.kind === "unreachable") {
    const next = pairing.finishedSetup
      ? "Start it with 'gaia start'"
      : "Finish setting it up with 'gaia up'";
    return (
      `GAIA's self-host install at ${pairing.install} isn't answering at ${pairing.origin}, so there is nothing to pair with.\n` +
      `${next}, or ${PAIR_WITH_CLOUD}.`
    );
  }
  if (pairing.health.redirectedTo) {
    return (
      `GAIA's install at ${pairing.install} redirected ${pairing.origin}/api/v1/ping to ${pairing.health.redirectedTo}, a different origin.\n` +
      `That answer says nothing about this install, so it isn't a pairing target: check 'gaia status', or ${PAIR_WITH_CLOUD}.`
    );
  }
  return (
    `GAIA's install at ${pairing.install} answered HTTP ${pairing.health.status} (${pairing.health.contentType}) at ${pairing.origin}, not GAIA's health JSON.\n` +
    `Either another program holds that port, or the proxy is up without its API: check 'gaia status', or ${PAIR_WITH_CLOUD}.`
  );
}
