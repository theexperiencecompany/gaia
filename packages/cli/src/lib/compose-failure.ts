/**
 * Name why a `docker compose` run failed in plain words, with the next step,
 * instead of dumping its output. The raw output stays in a log file the
 * error points to.
 * @module lib/compose-failure
 */

import { serviceName } from "./display-names.js";
import type { ReleaseImageGap } from "./image-availability.js";

/** What failed and what to do next. */
export interface ComposeFailure {
  cause: string;
  next: string;
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
    next: `Update the CLI (curl -fsSL https://heygaia.io/install.sh | sh) and run it again, or build from source: ${rebuildCommand}.`,
  };
}

type Matcher = (text: string, ctx: FailureContext) => ComposeFailure | null;

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
  return {
    cause: `Port ${port ?? "GAIA needs"} is already used by another program.`,
    next: "Stop that program, or pick another port: gaia up --web-port <port>.",
  };
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
  const name = serviceName(service.replace(/^gaia-(selfhost|dev)-/, ""));
  return {
    cause: `${name} started but never became healthy.`,
    next: "See what it logged with 'gaia logs', then try again.",
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
  for (const matcher of [archMissing, imageMissing, portTaken, unhealthy]) {
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
    super(
      [failure.cause, failure.next, `Full log: ${logPath}`]
        .filter(Boolean)
        .join("\n"),
    );
    this.name = "ComposeError";
    this.failure = failure;
    this.logPath = logPath;
  }
}
