/**
 * State management for the CLI application.
 * Uses an event-based pattern for React/Ink integration.
 * @module store
 */

import { EventEmitter } from "events";

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
  /** Arbitrary data storage for step-specific state */
  // biome-ignore lint: Allow any for flexible state storage
  data: Record<string, any>;
  /** Current input request waiting for user response */
  // biome-ignore lint: Allow any for flexible meta data
  inputRequest: { id: string; meta?: any } | null;
}

/**
 * Central state store for the CLI application.
 * Extends EventEmitter to notify React components of state changes.
 *
 * Uses a throttled emit for high-frequency updates (updateData, setStatus)
 * and immediate emit for user-facing changes (setStep, setError, waitForInput, submitInput).
 *
 * @example
 * const store = new CLIStore();
 * store.on('change', (state) => console.log(state));
 * store.setStep('Prerequisites');
 */
export class CLIStore extends EventEmitter {
  private state: CLIState = {
    step: "init",
    status: "",
    error: null,
    data: {},
    inputRequest: null,
  };
  // biome-ignore lint: Allow any for flexible input resolver
  private inputResolver: ((value: any) => void) | null = null;
  private emitTimer: ReturnType<typeof setTimeout> | null = null;
  private emitPending = false;

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
   * Sets or clears the current error.
   * When setting a non-null error, resolves any pending input with null
   * and clears the input request to prevent stuck promises.
   * @param error - Error to display, or null to clear
   */
  setError(error: Error | null): void {
    this.state.error = error;
    if (error !== null && this.inputResolver) {
      this.inputResolver(null);
      this.inputResolver = null;
      this.state.inputRequest = null;
    }
    this.emitNow();
  }

  /**
   * Updates a specific key in the data store.
   * @param key - Data key to update
   * @param value - New value
   */
  // biome-ignore lint: Allow any for flexible state storage
  updateData(key: string, value: any): void {
    this.state.data = { ...this.state.data, [key]: value };
    this.scheduleEmit();
  }

  /**
   * Requests input from the user and waits for response.
   * @param id - Unique identifier for this input request
   * @param meta - Optional metadata for the input component
   * @returns Promise that resolves with the user's input
   */
  // biome-ignore lint: Allow any for flexible meta and return types
  waitForInput(id: string, meta?: any, timeoutMs?: number): Promise<any> {
    this.state.inputRequest = { id, meta };
    this.emitNow();
    return new Promise((resolve) => {
      this.inputResolver = resolve;

      if (timeoutMs != null) {
        const timer = setTimeout(() => {
          if (this.inputResolver) {
            this.inputResolver = null;
            this.state.inputRequest = null;
            this.emitNow();
            resolve(null);
          }
        }, timeoutMs);
        const queued = this.inputResolver;
        this.inputResolver = (value: unknown) => {
          clearTimeout(timer);
          queued(value);
        };
      }
    });
  }

  /**
   * Submits user input to resolve the pending waitForInput promise.
   * @param value - The user's input value
   */
  // biome-ignore lint: Allow any for flexible input types
  submitInput(value: any): void {
    if (this.inputResolver) {
      this.inputResolver(value);
      this.inputResolver = null;
      this.state.inputRequest = null;
      this.emitNow();
    }
  }
}

/**
 * Factory function to create a new CLI store instance.
 * @returns New CLIStore instance
 */
export const createStore = (): CLIStore => new CLIStore();
