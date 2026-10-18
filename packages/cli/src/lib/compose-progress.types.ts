import type { ProgressAmount } from "./progress.js";

export interface Layer {
  /** The image ref this layer is being pulled for. */
  image: string;
  current: number;
  total: number;
  done: boolean;
  /** Already on this computer: nothing to download. */
  present: boolean;
}

export type ImageState = "downloading" | "building" | "ready";

/** One line of `docker compose --progress json` output, as far as we read it. */
export interface ComposeEvent {
  id?: string;
  parent_id?: string;
  status?: string;
  text?: string;
  details?: string;
  current?: number;
  total?: number;
  error?: boolean;
  message?: string;
  /** BuildKit vertices: one per build step, `[stage n/m] RUN ...`. */
  vertexes?: { digest: string; name?: string; completed?: string }[];
}

export interface ComposeProgressState {
  /** Image ref -> where it stands. */
  images: Map<string, ImageState>;
  layers: Map<string, Layer>;
  /** Build steps (BuildKit vertices named `[n/m] ...`) -> completed yet. */
  steps: Map<string, { name: string; done: boolean }>;
  /** Service -> up yet (started by this run, or already running). */
  containers: Map<string, boolean>;
  /** Services this run started; an already-running one is not among them. */
  started: Set<string>;
  /** Services compose is waiting on to pass their health check before it starts the next. */
  awaitingHealth: Set<string>;
  /** Service -> stopped yet, for `down`; in the order they began to stop. */
  stopping: Map<string, boolean>;
  /** Finished steps worth showing, newest last. */
  finished: string[];
  /** Error messages compose reported, in order. */
  errors: string[];
  /** Layer short id -> size, from the registries before the pull began; empty when unknown. */
  expectedLayers: ReadonlyMap<string, number>;
  /** Largest estimated download total shown so far, so the total never shrinks. */
  downloadTotal: number;
}

/** What compose is doing, for a heading above the phase line. */
export type ComposeStage =
  | "building"
  | "downloading"
  | "unpacking"
  | "starting"
  | "stopping";

export interface ComposePhase {
  stage: ComposeStage;
  /** One line naming the phase and how far along it is. */
  label: string;
  /** The same without the phase's name, for under a heading that already says it. */
  detail?: string;
  /** 0-100 for the bar. */
  percent: number;
  amount?: ProgressAmount;
}
