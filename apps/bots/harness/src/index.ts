/**
 * @module @gaia/bot-harness
 *
 * `gaia-sim` — a simulation harness that drives the real GAIA bot pipeline
 * while emulating a platform and recording a JSONL transcript. See the
 * `driving-gaia` skill for end-to-end usage.
 */

export { HarnessAdapter, type SimulateOptions } from "./adapter";
export {
  EMULATABLE_PLATFORMS,
  isEmulatablePlatform,
  type PlatformEmulation,
  resolveEmulation,
} from "./emulation";
export {
  type LinkedDevUser,
  linkDevUser,
  runScenario,
  type ScenarioResult,
  type SendResult,
  sendOneShot,
} from "./runner";
export type {
  Scenario,
  ScenarioAssertion,
  ScenarioTurn,
} from "./scenario.types";
export { TranscriptRecorder } from "./transcript";
export type * from "./transcript.types";
