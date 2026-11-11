/**
 * Name why a `docker compose` run failed in plain words, with the next step,
 * instead of dumping its output. The raw output stays in a log file the
 * error points to.
 * @module lib/compose-failure
 */

import { serviceName } from "./display-names.js";
import type { ReleaseImageGap } from "./image-availability.js";
import { homeRelative } from "./paths.js";
import { cliChannel, cliInstallCommand } from "./release.js";
import { CLI_VERSION } from "./version.js";

/** What failed and what to do next. */
export interface ComposeFailure {
  cause: string;
  next: string;
  /** The compose service that failed, when one is named (an unhealthy container). */
  service?: string;
  /** That service's last log lines, when they were fetched. */
  logTail?: string[];
}

/** The command that retries with a local build, e.g. "gaia up --build". */
export interface FailureContext {
  rebuildCommand: string;
}

const GAIA_IMAGE_RE = /ghcr\.io\/theexperiencecompany\/(gaia[\w-]*):([\w.-]+)/;
const IMAGE_ROLES: Record<string, string> = {
  gaia: "API",
  "gaia-web": "web app",
};

function gaiaImage(text: string): { name: string; tag: string } | null {
  const match = GAIA_IMAGE_RE.exec(text);
  return match?.[1] && match[2] ? { name: match[1], tag: match[2] } : null;
}

function imageLabel(name: string): string {
  const role = IMAGE_ROLES[name];
  return role ? `GAIA's ${role} image (${name})` : `the ${name} image`;
}

/** Why a release's image cannot run here, and how to get GAIA anyway. */
export function explainImageGap(
  gap: ReleaseImageGap,
  rebuildCommand: string,
): ComposeFailure {
  const [name = gap.image, tag = ""] = gap.image.split(":");
  if (gap.kind === "wrong-cpu") {
    return {
      cause: `${imageLabel(name)} at ${tag} has no build for this computer's processor (${gap.arch}).`,
      next: `Build it on this machine instead: ${rebuildCommand} (15-30 minutes).`,
    };
  }
  return {
    cause: `GAIA ${tag} isn't published: ${imageLabel(name)} doesn't exist in the registry.`,
    next: `Update the CLI (${cliInstallCommand(cliChannel(CLI_VERSION))}) and run it again, or build from source: ${rebuildCommand}.`,
  };
}

type Matcher = (text: string, ctx: FailureContext) => ComposeFailure | null;

/** The ports a --domain install publishes, which --web-port cannot move. */
const DOMAIN_PORTS: ReadonlySet<number> = new Set([80, 443]);

const archMissing: Matcher = (text, ctx) => {
  const arch = /no matching manifest for linux\/([\w]+)/.exec(text)?.[1];
  if (!arch) return null;
  const image = gaiaImage(text);
  if (image) {
    return explainImageGap(
      { kind: "wrong-cpu", image: `${image.name}:${image.tag}`, arch },
      ctx.rebuildCommand,
    );
  }
  return {
    cause: `One of GAIA's images has no build for this computer's processor (${arch}).`,
    next: `Build it on this machine instead: ${ctx.rebuildCommand} (15-30 minutes).`,
  };
};

const imageMissing: Matcher = (text, ctx) => {
  if (
    !/manifest unknown|: not found|failed to resolve reference|No such image/.test(
      text,
    )
  ) {
    return null;
  }
  const image = gaiaImage(text);
  if (image) {
    return explainImageGap(
      { kind: "not-published", image: `${image.name}:${image.tag}` },
      ctx.rebuildCommand,
    );
  }
  const local = /No such image: ([\w./-]+:[\w.-]+)/.exec(text)?.[1];
  return {
    cause: local
      ? `The image ${local} was never built on this machine.`
      : "An image GAIA needs could not be found.",
    next: `Build the images here: ${ctx.rebuildCommand}.`,
  };
};

const portTaken: Matcher = (text) => {
  const port =
    /Bind for [\d.:[\]]*:(\d+) failed/.exec(text)?.[1] ??
    /listen tcp[46]? [\d.:[\]]*:(\d+): bind: address already in use/.exec(
      text,
    )?.[1];
  if (!port && !/port is already allocated|address already in use/.test(text)) {
    return null;
  }
  const domainPort = port !== undefined && DOMAIN_PORTS.has(Number(port));
  return {
    cause: `Port ${port ?? "GAIA needs"} is already used by another program.`,
    next: domainPort
      ? `A domain needs ports 80 and 443: stop the program on port ${port} (see it with 'sudo ss -ltnp'), then run 'gaia up' again.`
      : "Stop that program, or pick another port: gaia up --web-port <port>.",
  };
};

/** Where the Docker daemon, which pulls images, takes its proxy; it ignores this shell's HTTPS_PROXY. */
const DAEMON_PROXY_HINT =
  "set it for Docker itself ('proxies' in /etc/docker/daemon.json, or Docker Desktop > Settings > Resources > Proxies), restart Docker";

/** The registry a pull error names, e.g. ghcr.io. */
function registryHost(text: string): string {
  return (
    /lookup ([\w.-]+)/.exec(text)?.[1] ??
    /https?:\/\/([\w.-]+)\/v2\//.exec(text)?.[1] ??
    "the image registry"
  );
}

/** Network failures named by what to change: Docker's proxy, DNS, the clock, or the route out. */
const networkFailure: Matcher = (text) => {
  const host = registryHost(text);
  if (/proxyconnect/i.test(text)) {
    return {
      cause: `Docker couldn't reach its proxy on the way to ${host}.`,
      next: `Check the proxy address Docker uses: ${DAEMON_PROXY_HINT}, then try again.`,
    };
  }
  if (/x509: certificate has expired or is not yet valid/i.test(text)) {
    return {
      cause: `This machine's clock is wrong, so ${host}'s certificate looks invalid.`,
      next: "Check the time with 'timedatectl', turn on time sync with 'sudo timedatectl set-ntp true', then try again.",
    };
  }
  if (/x509: certificate signed by unknown authority/i.test(text)) {
    return {
      cause: `Something on this network intercepts HTTPS to ${host} (a TLS-inspecting proxy).`,
      next: "Add that proxy's CA certificate to this machine's trusted certificates, restart Docker, then try again.",
    };
  }
  if (
    /lookup [\w.-]+.*(no such host|server misbehaving|i\/o timeout)/i.test(text)
  ) {
    return {
      cause: `This machine couldn't look up ${host} (DNS).`,
      next: "Check the DNS servers in /etc/resolv.conf (or 'dns' in /etc/docker/daemon.json), then try again.",
    };
  }
  if (
    /i\/o timeout|TLS handshake timeout|Client\.Timeout exceeded|context deadline exceeded/i.test(
      text,
    )
  ) {
    return {
      cause: `Connecting to ${host} timed out.`,
      next: `If this network needs a proxy, ${DAEMON_PROXY_HINT}; otherwise allow outbound HTTPS (port 443). Then try again.`,
    };
  }
  return null;
};

const SIMPLE_MATCHERS: readonly [RegExp, ComposeFailure][] = [
  [
    /permission denied while trying to connect/i,
    {
      cause: "Docker refused your user.",
      next: "Log out and back in (or run 'newgrp docker'), then try again.",
    },
  ],
  [
    /Cannot connect to the Docker daemon|Is the docker daemon running/i,
    {
      cause: "Docker stopped running.",
      next: "Start Docker (sudo systemctl start docker, or open OrbStack / Docker Desktop), then try again.",
    },
  ],
  [
    /no space left on device/i,
    {
      cause: "The disk is full.",
      next: "Free some space ('docker system prune' removes unused images), then try again.",
    },
  ],
  [
    /toomanyrequests|rate limit/i,
    {
      cause: "The image registry is limiting downloads from this network.",
      next: "Wait a few minutes, then try again.",
    },
  ],
  [
    /i\/o timeout|TLS handshake timeout|no such host|network is unreachable|connection reset by peer|dial tcp/i,
    {
      cause: "GAIA's images could not be downloaded (network error).",
      next: "Check this machine's internet connection, then try again.",
    },
  ],
];

const unhealthy: Matcher = (text) => {
  const service = /container ([\w-]+?)(?:-\d+)? is unhealthy/.exec(text)?.[1];
  if (!service) return null;
  const composeService = service.replace(/^gaia-(selfhost|dev)-/, "");
  return {
    cause: `GAIA's ${serviceName(composeService)} didn't start.`,
    next: "Try: gaia doctor",
    service: composeService,
  };
};

/** The last line that reads like an error, for failures nothing above names. */
function lastErrorLine(lines: readonly string[]): string {
  const errorLine = [...lines]
    .reverse()
    .find((line) => /error|failed|denied/i.test(line));
  return (errorLine ?? lines.at(-1) ?? "docker compose failed").trim();
}

/** Why compose failed, from its error messages and output lines. */
export function explainComposeFailure(
  errors: readonly string[],
  lines: readonly string[],
  ctx: FailureContext,
): ComposeFailure {
  const text = [...errors, ...lines].join("\n");
  for (const matcher of [
    archMissing,
    imageMissing,
    portTaken,
    unhealthy,
    networkFailure,
  ]) {
    const failure = matcher(text, ctx);
    if (failure) return failure;
  }
  for (const [pattern, failure] of SIMPLE_MATCHERS) {
    if (pattern.test(text)) return failure;
  }
  return {
    cause: `Docker Compose failed: ${errors.at(-1) ?? lastErrorLine(lines)}`,
    next: "",
  };
}

/** A failed compose run: the plain cause, the next step, and the full log. */
export class ComposeError extends Error {
  readonly failure: ComposeFailure;
  readonly logPath: string;

  constructor(failure: ComposeFailure, logPath: string) {
    // What failed, why (its own last words), where the full log is, then the
    // most actionable line last.
    const tail = failure.logTail?.length
      ? ["Its last log lines:", ...failure.logTail.map((line) => `  ${line}`)]
      : [];
    super(
      [
        failure.cause,
        ...tail,
        `Full log: ${homeRelative(logPath)}`,
        failure.next,
      ]
        .filter(Boolean)
        .join("\n"),
    );
    this.name = "ComposeError";
    this.failure = failure;
    this.logPath = logPath;
  }
}
