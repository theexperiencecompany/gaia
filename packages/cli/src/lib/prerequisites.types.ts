export type CheckResult = "success" | "error" | "missing" | "pending";

export interface PrerequisiteInfo {
  name: string;
  installUrl: string;
  installed: boolean;
  working: boolean;
  /** The daemon answered, but refused this user (socket permissions). */
  permissionDenied?: boolean;
  errorMessage?: string;
}

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

export interface EnsureDockerOptions {
  /** `--yes`: consent to installing Docker and joining the docker group. */
  assumeYes?: boolean;
}
