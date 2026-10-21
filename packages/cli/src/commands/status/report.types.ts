import type { DependencyReadiness } from "../../lib/dependency-readiness.js";
import type { CertificateState } from "../../lib/domain-reachability.js";
import type { DockerStatus, ServiceStatus } from "../../lib/healthcheck.js";

export interface StatusFacts {
  /** "~/gaia (self-host)", or why there is nothing to check. */
  install: string;
  installed: boolean;
  docker?: DockerStatus;
  readiness?: DependencyReadiness;
  /** Developer mode's host-port probes. */
  services: ServiceStatus[];
  webUrl?: string;
  /** null when the API could not say. */
  setupComplete: boolean | null;
  /** The domain's certificate, on an install `gaia up --domain` set up for a public CA. */
  certificate?: CertificateState;
}

export interface StatusItem {
  ok: boolean;
  name: string;
}

export interface StatusRow {
  label: string;
  items: StatusItem[];
  /** Said instead of, or after, the items: a fix for a red row, or a hint. */
  note?: string;
  tone: "ok" | "warn" | "fail" | "dim";
}

export interface StatusReport {
  headline: { kind: "ok" | "fail" | "warn"; text: string; url?: string };
  /** What to do, said under the headline (a Docker problem's fix). */
  hint?: string;
  rows: StatusRow[];
  /** True when a part GAIA needs is down: `gaia status` then exits 1. */
  unhealthy: boolean;
}
