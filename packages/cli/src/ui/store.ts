/**
 * State management for the CLI application.
 * Uses an event-based pattern for React/Ink integration.
 * @module store
 */

import { EventEmitter } from 'events';

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
 * @example
 * const store = new CLIStore();
 * store.on('change', (state) => console.log(state));
 * store.setStep('Prerequisites');
 */
export class CLIStore extends EventEmitter {
  private state: CLIState = {
    step: 'init',
    status: '',
    error: null,
    data: {},
    inputRequest: null,
  };
  // biome-ignore lint: Allow any for flexible input resolver
  private inputResolver: ((value: any) => void) | null = null;

  constructor() {
    super();
  }

  /**
   * Gets the current state snapshot.
   * @returns Current CLI state
   */
  get currentState(): CLIState {
    return this.state;
  }

  /**
   * Sets the current step in the setup flow.
   * @param step - Step identifier
   */
  setStep(step: string): void {
    this.state.step = step;
    this.emit('change', this.state);
  }

  /**
   * Sets the status message displayed in the footer.
   * @param status - Status message to display
   */
  setStatus(status: string): void {
    this.state.status = status;
    this.emit('change', this.state);
  }

  /**
   * Sets or clears the current error.
   * @param error - Error to display, or null to clear
   */
  setError(error: Error | null): void {
    this.state.error = error;
    this.emit('change', this.state);
  }

  /**
   * Updates a specific key in the data store.
   * @param key - Data key to update
   * @param value - New value
   */
  // biome-ignore lint: Allow any for flexible state storage
  updateData(key: string, value: any): void {
    this.state.data = { ...this.state.data, [key]: value };
    this.emit('change', this.state);
  }

  /**
   * Requests input from the user and waits for response.
   * @param id - Unique identifier for this input request
   * @param meta - Optional metadata for the input component
   * @returns Promise that resolves with the user's input
   */
  // biome-ignore lint: Allow any for flexible meta and return types
  waitForInput(id: string, meta?: any): Promise<any> {
    this.state.inputRequest = { id, meta };
    this.emit('change', this.state);
    return new Promise((resolve) => {
      this.inputResolver = resolve;
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
      this.emit('change', this.state);
    }
  }
}

/**
 * Factory function to create a new CLI store instance.
 * @returns New CLIStore instance
 */
export const createStore = (): CLIStore => new CLIStore();
