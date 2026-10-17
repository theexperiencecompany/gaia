export type CheckResult = "success" | "error" | "missing" | "pending";

export interface PortCheckResult {
  port: number;
  service: string;
  available: boolean;
  usedBy?: string;
  alternative?: number;
}

/** Outcome of {@link ensureDocker}. */
export type DockerReadiness =
  /** Docker answers this process; carry on. */
  | "ready"
  /**
   * This user was just granted the docker group, which only a new process
   * picks up: the command runner relaunches in the docker group and the flow
   * must stop here (see lib/docker-group.ts).
   */
  | "relaunch";

export interface InstallConsentOptions {
  /** `--yes`: consent to installing a missing prerequisite (and joining the docker group). */
  assumeYes?: boolean;
}
