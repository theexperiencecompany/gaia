/**
 * The two optional hosts a self-host with a domain can share through: a link
 * domain whose /<slug> redirects to GAIA's /l/<slug> page, and a content host
 * that serves shared files' bytes away from GAIA's own origin and cookies.
 * The compose env file records them for Caddy; apps/api/.env gets the API
 * settings they imply.
 * @module lib/share-domains
 */

import type { CLIStore } from "../ui/store.js";
import { SHARE_DOMAIN_KINDS } from "./env-writer.js";
import { generateMachineSecret } from "./machine-secrets.js";
import type {
  ShareDomainFlags,
  ShareDomainKind,
  ShareDomainRequest,
  ShareDomains,
} from "./share-domains.types.js";

/** The input `gaia up` asks a share domain with; an empty answer skips it. */
export const SHARE_DOMAIN_INPUT = "share_domain";

const SHORTLINK_BASE_URL_KEY = "SHORTLINK_BASE_URL";
const CONTENT_URL_TEMPLATE_KEY = "LINK_CONTENT_URL_TEMPLATE";
const CONTENT_SIGNING_KEY_KEY = "LINK_CONTENT_SIGNING_KEY";

/** The API's content route; the API fills {content_id} per snapshot. */
const CONTENT_ROUTE = "/api/v1/usercontent/{content_id}";

const FLAG_NAMES: Record<ShareDomainKind, string> = {
  link: "--link-domain",
  usercontent: "--usercontent-domain",
};

const ASKING_STATUS: Record<ShareDomainKind, string> = {
  link: "Choosing a short-link domain…",
  usercontent: "Choosing a domain for shared files…",
};

/** A bare DNS name: labels of letters, digits and inner hyphens, at least two of them. */
const HOSTNAME_RE =
  /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

/**
 * Set the API settings the share domains imply, and remove the ones a domain
 * no longer served leaves behind: the CLI owns these keys on a self-host.
 */
export function applyShareDomainApiEnv(
  env: Record<string, string>,
  domains: ShareDomains,
): void {
  if (domains.link) {
    env[SHORTLINK_BASE_URL_KEY] = `https://${domains.link}`;
  } else {
    // Unset, the API mints links on this instance's own /l page.
    delete env[SHORTLINK_BASE_URL_KEY];
  }
  if (domains.usercontent) {
    env[CONTENT_URL_TEMPLATE_KEY] =
      `https://${domains.usercontent}${CONTENT_ROUTE}`;
    env[CONTENT_SIGNING_KEY_KEY] ??= generateMachineSecret();
  } else {
    delete env[CONTENT_URL_TEMPLATE_KEY];
    delete env[CONTENT_SIGNING_KEY_KEY];
  }
}

/** Why a share domain cannot be used, or null when it can. */
function shareDomainProblem(
  domain: string,
  appDomain: string,
  chosen: ShareDomains,
): string | null {
  if (!HOSTNAME_RE.test(domain)) {
    return `${domain} is not a domain name. Enter just the name, like share.example.com.`;
  }
  if (domain === appDomain) {
    return `${domain} serves GAIA itself. Use a different name, like share.${appDomain}.`;
  }
  if (Object.values(chosen).includes(domain)) {
    return `${domain} is already the other share domain. Use a different name for each.`;
  }
  return null;
}

function normalise(domain: string): string {
  return domain.trim().toLowerCase();
}

interface ShareDomainPlan {
  /** The domain GAIA is served at this run; share domains need one. */
  appDomain: string | undefined;
  flags: ShareDomainFlags;
  /** What the compose env file holds from an earlier run. */
  recorded: ShareDomains;
  /** Whether a person can answer a prompt (a TTY, without --yes). */
  canAsk: boolean;
}

/**
 * The share domains a run serves: a flag, else the recorded one, else a
 * prompt when someone can answer it. A flag that cannot be used fails the
 * run; a prompt answer that cannot be used is asked again with the reason.
 */
export async function resolveShareDomains(
  store: CLIStore,
  plan: ShareDomainPlan,
): Promise<ShareDomains> {
  const { appDomain, flags, recorded, canAsk } = plan;
  if (!appDomain) {
    const flagged = SHARE_DOMAIN_KINDS.find((kind) => flags[kind]);
    if (flagged) {
      throw new Error(
        `${FLAG_NAMES[flagged]} sits beside GAIA's own domain. Run gaia up --domain <domain> ${FLAG_NAMES[flagged]} ${flags[flagged]}.`,
      );
    }
    return {};
  }

  const domains: ShareDomains = {};
  for (const kind of SHARE_DOMAIN_KINDS) {
    const flag = flags[kind];
    if (flag === false) continue;
    if (flag) {
      const domain = normalise(flag);
      const problem = shareDomainProblem(domain, appDomain, domains);
      if (problem) throw new Error(`${FLAG_NAMES[kind]}: ${problem}`);
      domains[kind] = domain;
    } else if (recorded[kind]) {
      domains[kind] = recorded[kind];
    } else if (canAsk) {
      const answer = await askShareDomain(store, kind, appDomain, domains);
      if (answer) domains[kind] = answer;
    }
  }
  return domains;
}

async function askShareDomain(
  store: CLIStore,
  kind: ShareDomainKind,
  appDomain: string,
  chosen: ShareDomains,
): Promise<string> {
  let retry: string | undefined;
  for (;;) {
    const request: ShareDomainRequest = retry
      ? { kind, appDomain, retry }
      : { kind, appDomain };
    const answer = normalise(
      await store.ask(SHARE_DOMAIN_INPUT, ASKING_STATUS[kind], request),
    );
    if (!answer) return "";
    const problem = shareDomainProblem(answer, appDomain, chosen);
    if (!problem) return answer;
    retry = problem;
  }
}
