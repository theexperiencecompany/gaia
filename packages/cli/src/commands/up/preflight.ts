/**
 * What `gaia up` checks before it downloads anything: that this machine can
 * hold GAIA, and that a --domain points here. A real blocker stops the run;
 * anything tight or not yet right becomes one line under the step.
 * @module commands/up/preflight
 */

import { checkDomainDns } from "../../lib/domain-reachability.js";
import {
  getDockerRootDir,
  judgeDisk,
  judgeMemory,
  readDockerDiskFree,
  readDockerMemoryBytes,
  thisMemoryHost,
} from "../../lib/host-resources.js";
import type {
  DiskPurpose,
  ResourceVerdict,
} from "../../lib/host-resources.types.js";

/** A reason the run must stop, or lines to show while it carries on. */
export interface PreflightFindings {
  blocker?: string;
  warnings: string[];
}

function finding(
  findings: PreflightFindings,
  resource: "memory" | "disk space",
  verdict: ResourceVerdict,
): void {
  if (verdict.level === "fail") {
    findings.blocker ??= `Not enough ${resource}: ${verdict.detail}.\n${verdict.fix}`;
  } else if (verdict.level === "warn") {
    findings.warnings.push(`${verdict.detail}. ${verdict.fix}`);
  }
}

/** Memory, and free disk where Docker keeps images (unknown inside Docker Desktop's VM). */
export async function checkHostResources(
  purpose: DiskPurpose,
): Promise<PreflightFindings> {
  const findings: PreflightFindings = { warnings: [] };
  finding(
    findings,
    "memory",
    judgeMemory(await readDockerMemoryBytes(), thisMemoryHost()),
  );
  const rootDir = await getDockerRootDir();
  const free = await readDockerDiskFree(rootDir);
  if (free !== null) {
    finding(findings, "disk space", judgeDisk(free, rootDir, purpose));
  }
  return findings;
}

/** The warning for a domain whose DNS doesn't point here; a failed lookup is a warning too, never a stop. */
export async function domainDnsWarning(domain: string): Promise<string | null> {
  try {
    return await checkDomainDns(domain);
  } catch (e) {
    return `Couldn't look up ${domain} in DNS (${(e as Error).message}); HTTPS needs it to point at this machine.`;
  }
}
