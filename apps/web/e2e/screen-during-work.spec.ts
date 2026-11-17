import { expect, test } from "@playwright/test";
import { APPROVAL_COPY } from "../src/features/chat/constants/approvalCopy";
import {
  loadingRow,
  MODEL_ERROR_LINE,
  SIM_ENABLED,
  sendMessage,
} from "./harness";
import { askBefore } from "./screen-fixtures";
import {
  expectTodos,
  expectUserOrder,
  finish,
  HOLD_MS,
  heldWork,
  openNewChat,
  sendAndOpen,
  TURN_MS,
  todo,
  untilBotLine,
} from "./screen-flows";
import {
  botLinesReading,
  currentScreen,
  toolSections,
} from "./screen-timeline";

/**
 * What a user sends or taps while GAIA is still working: a side question, an
 * addition, a stop, an approval with a change. Each flow asserts what the
 * screen shows while the work runs and after, the same way screen-over-time does.
 */

// The flows share one dev user and flip its approval preferences: one at a time, in order.
test.describe.configure({ mode: "default" });

test.describe("screen during work", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the sim stack (`mise dev --sim`, E2E_SIM=1).",
  );
  test.setTimeout(5 * TURN_MS);
  test.beforeEach(async () => askBefore([]));

  // Bugs 1 and 15: a side question during comms' own lookup threw the lookup away.
  test("a side question while GAIA is looking something up is answered, and so is the lookup", async ({
    page,
  }) => {
    await openNewChat(page);
    // The lookup is comms' own tool, then the model holds its write-up: the side question lands mid-run.
    await sendAndOpen(
      page,
      `research artemis [[tool:web_search_tool {"query_text":"artemis news"}]] [[wait:${HOLD_MS}]] [[say:Research summary.]]`,
    );
    // Sent once the lookup's result is on screen, while the model holds its write-up.
    await expect
      .poll(
        async () => (await currentScreen(page)).some((i) => i.role === "bot"),
        { timeout: TURN_MS },
      )
      .toBe(true);
    await expect(loadingRow(page)).toBeVisible();
    await sendMessage(page, "quick side question: 15% of 240? [[say:36.]]");
    await untilBotLine(page, "36.");
    const live = await finish(page, "Research summary.");
    expectUserOrder(live, ["research artemis", "quick side question"]);
    expect(
      botLinesReading(live, "Research summary."),
      "the lookup is still written up, once",
    ).toBe(1);
    expect(botLinesReading(live, "36."), "the side question answered").toBe(1);
  });

  test("an addition during running work joins that work, and one result covers it", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, heldWork("ad", "Pantry stocked."));
    await untilBotLine(page, "ad-1");
    await sendMessage(
      page,
      `also add oat milk ${todo("ad-oat")} [[say:Oat milk too.]]`,
    );
    const live = await finish(page, "Oat milk too.");
    expectUserOrder(live, ["work", "also add oat milk"]);
    expect(toolSections(live), "the addition ran inside the running work").toBe(
      1,
    );
    for (const title of ["ad-1", "ad-2", "ad-oat"]) {
      expect(botLinesReading(live, title), `${title} ran once`).toBe(1);
    }
    expect(botLinesReading(live, "Oat milk too."), "one result").toBe(1);
  });

  // Bug 24: a stop while a tool call was in flight left the call unanswered in the
  // executor's thread, and the provider refused every later run in the conversation.
  test("a stop while a tool is running leaves the chat able to run new work", async ({
    page,
  }) => {
    const subagentTask = `look into it [[wait:${3 * HOLD_MS}]] [[say:Sub done.]]`;
    await openNewChat(page);
    await sendAndOpen(
      page,
      `research [[tool:spawn_subagent ${JSON.stringify({ task: subagentTask, background: false })}]] [[say:Never said.]]`,
    );
    // The subagent's model holds its step, so the executor's spawn call is in flight.
    await expect(loadingRow(page)).toHaveText(/Working on part of it/, {
      timeout: TURN_MS,
    });
    await page.getByRole("button", { name: "Stop generation" }).click();
    await expect(page.getByText("Stopped").first()).toBeVisible({
      timeout: TURN_MS,
    });
    await expect(loadingRow(page)).toHaveCount(0, { timeout: TURN_MS });

    await sendMessage(
      page,
      `next ${todo("after-stop")} [[say:Added after-stop.]]`,
    );
    const live = await finish(page, "Added after-stop.");
    expect(botLinesReading(live, "after-stop"), "the new work ran").toBe(1);
    expect(botLinesReading(live, "Never said.")).toBe(0);
    await expect(page.getByText(MODEL_ERROR_LINE)).toHaveCount(0);
  });
});

test.describe("screen during work — approvals", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the sim stack (`mise dev --sim`, E2E_SIM=1).",
  );
  test.setTimeout(5 * TURN_MS);
  test.beforeEach(async () => askBefore(["create_todo"]));
  test.afterEach(async () => askBefore([]));

  // Review #5: a note typed on the card was dropped and Approve ran the call as it stood.
  test("approving with a note asks again with the change, and the unchanged call never runs", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, `${todo("note-plain")} [[say:Added it.]]`);
    const card = page.getByText(APPROVAL_COPY.needsApproval).first();
    await expect(card).toBeVisible({ timeout: TURN_MS });
    // The note is the change; under the stub it scripts the work's next step.
    await page
      .getByPlaceholder(APPROVAL_COPY.feedbackPlaceholder)
      .fill(
        `call it note-changed ${todo("note-changed")} [[say:Added the changed one.]]`,
      );
    await page
      .getByRole("button", { name: APPROVAL_COPY.approve, exact: true })
      .click();

    await expect(
      page.getByText("Add “note-changed” to your todos"),
      "the work asks again with the change",
    ).toBeVisible({ timeout: TURN_MS });
    await expect(page.getByText(APPROVAL_COPY.needsApproval)).toHaveCount(1);
    await page
      .getByRole("button", { name: APPROVAL_COPY.approve, exact: true })
      .click();
    await finish(page, "Added the changed one.");
    await expectTodos(page, ["note-changed"], ["note-plain"]);
  });
});
