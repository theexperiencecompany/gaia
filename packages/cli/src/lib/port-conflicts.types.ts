/** Why a port must stay where it is: a domain needs 80/443, --web-port is the user's choice. */
export type FixedPortReason = "domain" | "web-port";

/** "ask": the prompt; "move": take the free alternative (--yes); "fail": no terminal to ask. */
export type PortConflictPolicy = "ask" | "move" | "fail";

export interface PortPlan {
  /** The host port each default port is bound to: earlier runs' choices and this run's flags. */
  planned: Record<number, number>;
  /** Default ports a flag pins, by why. */
  fixed: Partial<Record<number, FixedPortReason>>;
  policy: PortConflictPolicy;
}

export type PortResolution =
  | { overrides: Record<number, number>; moved: string[] }
  | { error: string };
