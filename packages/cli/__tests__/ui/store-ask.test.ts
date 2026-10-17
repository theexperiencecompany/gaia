import { describe, expect, it } from "vitest";
import { createStore } from "../../src/ui/store.js";

// cli-taste T20: `gaia up | cat` printed "Configuring DEEPGRAM_API_KEY…" for
// settings it filled itself, without asking anyone.
describe("CLIStore.ask", () => {
  it("takes a preset answer without saying what it would have asked", async () => {
    const store = createStore();
    store.setStatus("Configuring GAIA…");
    store.pushAnswerResolver((id) => (id === "env_var" ? "preset" : undefined));

    const value = await store.ask("env_var", "Configuring DEEPGRAM_API_KEY…", {
      varName: "DEEPGRAM_API_KEY",
    });

    expect(value).toBe("preset");
    expect(store.currentState.status).toBe("Configuring GAIA…");
  });

  it("says what it asks when a person has to answer", async () => {
    const store = createStore();

    const answer = store.ask("env_var", "Configuring DEEPGRAM_API_KEY…");
    expect(store.currentState.status).toBe("Configuring DEEPGRAM_API_KEY…");
    store.submitInput("typed");

    expect(await answer).toBe("typed");
  });
});
