import { describe, expect, it } from "vitest";
import { createStore } from "../../src/ui/store.js";

// cli-taste T20: `gaia up | cat` printed "Configuring DEEPGRAM_API_KEY…" for
// settings it filled itself, without asking anyone.
describe("CLIStore.ask", () => {
  it("takes a preset answer without saying what it would have asked", async () => {
    const store = createStore();
    store.setStatus("Configuring GAIA…");
    store.pushAnswerResolver({ env_var: () => "preset" });

    const value = await store.ask("env_var", "Configuring DEEPGRAM_API_KEY…", {
      varName: "DEEPGRAM_API_KEY",
    });

    expect(value).toBe("preset");
    expect(store.currentState.status).toBe("Configuring GAIA…");
  });

  it("says what it asks when a person has to answer", async () => {
    const store = createStore();

    const answer = store.ask("env_var", "Configuring DEEPGRAM_API_KEY…", {
      varName: "DEEPGRAM_API_KEY",
    });
    expect(store.currentState.status).toBe("Configuring DEEPGRAM_API_KEY…");
    store.submitInput("env_var", "typed");

    expect(await answer).toBe("typed");
  });
});

describe("CLIStore.waitForInput", () => {
  it("ends the wait with the error that ended the run", async () => {
    const store = createStore();
    const answer = store.waitForInput("update_confirm");
    const failure = new Error("Docker stopped answering.");

    store.setError(failure);

    await expect(answer).rejects.toBe(failure);
    expect(store.currentState.inputRequest).toBeNull();
  });

  it("drops an answer meant for another input", async () => {
    const store = createStore();
    const answer = store.waitForInput("uninstall_confirm");

    store.submitInput("update_confirm", true);
    expect(store.currentState.inputRequest?.id).toBe("uninstall_confirm");
    store.submitInput("uninstall_confirm", false);

    expect(await answer).toBe(false);
  });
});
