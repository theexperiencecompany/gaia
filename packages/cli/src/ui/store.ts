/**
 * State management for the CLI application.
 * Uses an event-based pattern for React/Ink integration.
 * @module store
 */

import { EventEmitter } from "events";
import type {
  AnswerResolver,
  CLIData,
  InputAnswer,
  InputArgs,
  InputId,
  InputMeta,
  InputRequest,
  PresetAnswers,
} from "./store.types.js";

const THROTTLE_MS = 150;

/**
 * Represents the complete state of the CLI application.
 */
export interface CLIState {
  /** Current step in the setup flow (e.g., 'Welcome', 'Prerequisites') */
  step: string;
  /** Status message displayed in the footer */
  status: string;
  /** Current error, if any */
  error: Error | null;
  /** Step-specific state; a key is absent until a flow sets it. */
  data: Partial<CLIData>;
  /** Current input request waiting for user response */
  inputRequest: InputRequest | null;
}

/** How to answer the input a flow is waiting on, keyed by its id. */
type PendingAnswers = {
  [K in InputId]?: (answer: InputAnswer<K>) => void;
};

/**
 * Central state store for the CLI application, extending EventEmitter to notify React
 * components of state changes. Emits are throttled for high-frequency updates (updateData,
 * setStatus) and immediate for user-facing changes (setStep, setError, waitForInput, submitInput).
 */
export class CLIStore extends EventEmitter {
  private state: CLIState = {
    step: "init",
    status: "",
    error: null,
    data: {},
    inputRequest: null,
  };
  private pendingAnswers: PendingAnswers = {};
  /** Ends the pending wait with the run's error, so no flow carries on past it. */
  private rejectPending: ((error: Error) => void) | null = null;
  private emitTimer: ReturnType<typeof setTimeout> | null = null;
  private emitPending = false;
  private readonly presetAnswers: PresetAnswers = {};
  private answerResolvers: AnswerResolver[] = [];

  /**
   * Answer these inputs without blocking on a UI prompt. Used by non-TTY
   * (plain text) handlers so flows that wait for a final "exit" confirmation
   * don't hang the process.
   */
  setAutoResolve(answers: PresetAnswers): void {
    Object.assign(this.presetAnswers, answers);
  }

  /**
   * Register a values layer consulted when an input request would otherwise
   * block on a UI prompt. Resolvers run in registration order (first
   * non-undefined answer wins); returning undefined passes control to the
   * next resolver, then to the interactive prompt.
   *
   * Used by `gaia up` to resolve prompt answers from CLI flags → saved
   * config → infrastructure defaults BEFORE any waitForInput blocks.
   */
  pushAnswerResolver(resolver: AnswerResolver): void {
    this.answerResolvers.push(resolver);
  }

  /**
   * Gets the current state snapshot.
   * @returns Current CLI state
   */
  get currentState(): CLIState {
    return this.state;
  }

  /**
   * Schedules a throttled emit — coalesces rapid state changes into
   * a single emit per THROTTLE_MS interval to prevent TUI jitter.
   */
  private scheduleEmit(): void {
    this.emitPending = true;
    if (!this.emitTimer) {
      this.emitTimer = setTimeout(() => {
        this.emitTimer = null;
        if (this.emitPending) {
          this.emitPending = false;
          this.emit("change", this.state);
        }
      }, THROTTLE_MS);
    }
  }

  /** Deliver a throttled change now: the run is ending and its last state must be drawn. */
  flush(): void {
    if (this.emitPending) this.emitNow();
  }

  /**
   * Emits immediately — flushes any pending throttled emit and
   * fires the change event right away. Used for user-facing changes
   * that need instant UI response.
   */
  private emitNow(): void {
    if (this.emitTimer) {
      clearTimeout(this.emitTimer);
      this.emitTimer = null;
    }
    this.emitPending = false;
    this.emit("change", this.state);
  }

  /**
   * Sets the current step in the setup flow.
   * @param step - Step identifier
   */
  setStep(step: string): void {
    this.state.step = step;
    this.emitNow();
  }

  /**
   * Sets the status message displayed in the footer.
   * @param status - Status message to display
   */
  setStatus(status: string): void {
    this.state.status = status;
    this.scheduleEmit();
  }

  /**
   * Sets or clears the current error. A non-null error also ends a pending
   * waitForInput, which rejects with that same error.
   */
  setError(error: Error | null): void {
    this.state.error = error;
    const reject = this.rejectPending;
    if (error !== null && reject) {
      this.clearPending();
      reject(error);
    }
    this.emitNow();
  }

  private clearPending(): void {
    this.pendingAnswers = {};
    this.rejectPending = null;
    this.state.inputRequest = null;
  }

  /** Set one data key; screens re-render on the next throttled emit. */
  updateData<K extends keyof CLIData>(key: K, value: CLIData[K]): void {
    this.state.data = { ...this.state.data, [key]: value };
    this.scheduleEmit();
  }

  /**
   * waitForInput that says what it is asking (as the status) only when a
   * person will actually be asked: an answer flags or saved config supply
   * is taken silently, so `gaia up` never flashes the names of settings it
   * fills itself.
   */
  ask<K extends InputId>(
    id: K,
    statusWhileAsking: string,
    ...args: InputArgs<K>
  ): Promise<InputAnswer<K>> {
    if (this.presetAnswer(id, args) === undefined) {
      this.setStatus(statusWhileAsking);
    }
    return this.waitForInput(id, ...args);
  }

  /** The answer a preset or a values layer gives, without asking anyone. */
  private presetAnswer<K extends InputId>(
    id: K,
    args: InputArgs<K>,
  ): InputAnswer<K> | undefined {
    const preset = this.presetAnswers[id];
    if (preset !== undefined) return preset;
    for (const resolver of this.answerResolvers) {
      const answer = resolver[id]?.(...args);
      if (answer !== undefined) return answer;
    }
    return undefined;
  }

  /**
   * Ask for an input and wait for its answer: a preset or values layer's,
   * else the screen's. Rejects with the run's error when one ends it first.
   */
  waitForInput<K extends InputId>(
    id: K,
    ...args: InputArgs<K>
  ): Promise<InputAnswer<K>> {
    const meta: InputMeta<K> = args[0];
    const preset = this.presetAnswer(id, args);
    if (preset !== undefined) {
      this.state.inputRequest = null;
      this.emitNow();
      return Promise.resolve(preset);
    }
    const request: InputRequest<K> = { id, meta };
    // An upcast TypeScript cannot prove: InputRequest<K> is one member of the union.
    this.state.inputRequest = request as InputRequest;
    this.emitNow();
    return new Promise((resolve, reject) => {
      this.pendingAnswers = {};
      this.pendingAnswers[id] = resolve;
      this.rejectPending = reject;
    });
  }

  /** Answer the input the screen is showing; a stale answer for another id is dropped. */
  submitInput<K extends InputId>(id: K, value: InputAnswer<K>): void {
    const resolve = this.pendingAnswers[id];
    if (!resolve) return;
    this.clearPending();
    resolve(value);
    this.emitNow();
  }
}

/**
 * Factory function to create a new CLI store instance.
 * @returns New CLIStore instance
 */
export const createStore = (): CLIStore => new CLIStore();
