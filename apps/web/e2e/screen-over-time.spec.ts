import { expect, type Page, test } from "@playwright/test";
import { APPROVAL_COPY } from "../src/features/chat/constants/approvalCopy";
import {
  firstShownAt,
  loadingGaps,
  loadingRow,
  longestBlindWorkMs,
  MODEL_ERROR_LINE,
  SIM_ENABLED,
  sendMessage,
  WEB_BASE_URL,
  watchConversation,
} from "./harness";
import {
  askBefore,
  backdateApproval,
  conversationIdOf,
} from "./screen-fixtures";
import {
  BREAK,
  expectTodos,
  expectUserOrder,
  finish,
  HOLD_MS,
  heldWork,
  openNewChat,
  roles,
  SWEEP_MS,
  sendAndOpen,
  TURN_MS,
  todo,
  untilBotLine,
} from "./screen-flows";
import {
  botLinesReading,
  currentScreen,
  expectReloadMatches,
  expectScreenOnlyGrew,
  recordScreen,
  settledScreen,
  timeline,
  toolSections,
} from "./screen-timeline";

/**
 * The server owns the conversation screen and pushes patches; the web renders
 * them. Each flow scripts the model (sim stub), records the rendered items at
 * every DOM change, and asserts the screen only grew — nothing reordered,
 * vanished or doubled — and that a reload shows exactly what was live.
 */

// The flows share one dev user and flip its approval preferences: one at a time, in order.
test.describe.configure({ mode: "default" });

test.describe("screen over time — chat", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the sim stack (`mise dev --sim`, E2E_SIM=1).",
  );
  test.setTimeout(5 * TURN_MS);
  test.beforeEach(async () => askBefore([]));

  test("a single reply lands under its question", async ({ page }) => {
    await openNewChat(page);
    await sendAndOpen(page, "hi [[say:Hello there.]]");
    const live = await finish(page, "Hello there.");
    expect(roles(live)).toEqual(["user", "bot"]);
    expect(live[1].text).toBe("Hello there.");
  });

  test("a second turn's reply lands under the second question, not above it", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, "one [[say:Answer one.]]");
    await settledScreen(page, "Answer one.", TURN_MS);
    await sendMessage(page, "two [[say:Answer two.]]");
    const live = await finish(page, "Answer two.");
    expectUserOrder(live, ["one", "two"]);
    const second = live.findIndex(
      (i) => i.role === "user" && i.text.startsWith("two"),
    );
    const answer = live.findIndex(
      (i) => i.role === "bot" && i.text.includes("Answer two."),
    );
    expect(answer).toBeGreaterThan(second);
  });

  // Once a reply shows text it is committed: a message arriving while it still streams is never
  // folded into it, and gets its own reply under it.
  test("a message sent while a reply is still streaming gets its own reply under it", async ({
    page,
  }) => {
    await openNewChat(page);
    const first = "Alpha beta gamma delta epsilon zeta eta theta iota kappa.";
    await sendAndOpen(page, `one [[pace:300]] [[say:${first}]]`);
    await expect
      .poll(
        async () =>
          (await currentScreen(page)).some(
            (i) => i.role === "bot" && i.text.startsWith("Alpha"),
          ),
        { timeout: TURN_MS },
      )
      .toBe(true);
    expect(
      botLinesReading(await currentScreen(page), first),
      "the first reply is still streaming when the second message is sent",
    ).toBe(0);
    await sendMessage(page, "two [[say:Answer two.]]");
    const live = await finish(page, "Answer two.");
    expectUserOrder(live, ["one", "two"]);
    expect(roles(live), "each message has its own reply, under it").toEqual([
      "user",
      "bot",
      "user",
      "bot",
    ]);
    expect(live[1].text).toBe(first);
    expect(live[3].text).toBe("Answer two.");
  });

  test("a hand-off preamble stays on screen and the reply follows below it", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      `[[pace:40]] [[narrate:Let me check that.]] ${todo("pa-1")} [[say:Checked it.]]`,
    );
    const live = await finish(page, "Checked it.");
    expect(
      botLinesReading(live, "Let me check that."),
      "the preamble stays, once",
    ).toBe(1);
    const said = live
      .filter((item) => item.role === "bot")
      .flatMap((item) => item.text.split("\n"));
    expect(
      said.findIndex((line) => line.includes("Checked it.")),
      "the reply follows below the preamble",
    ).toBeGreaterThan(
      said.findIndex((line) => line.includes("Let me check that.")),
    );
    expect(toolSections(live)).toBe(1);
  });

  test("a multi-bubble reply streams its parts in order under its question", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      `three parts [[pace:40]] [[say:Part one.${BREAK}Part two.${BREAK}Part three.]]`,
    );
    const live = await finish(page, "Part three.");
    expect(live[0].role).toBe("user");
    const lines = live.slice(1).flatMap((i) => i.text.split("\n"));
    expect(lines.filter((l) => l.startsWith("Part "))).toEqual([
      "Part one.",
      "Part two.",
      "Part three.",
    ]);
  });

  test("a reply with tools shows one section with one card per call, each with its output", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      `two todos ${todo("rt-1")} ${todo("rt-2")} [[say:Both added.]]`,
    );
    const live = await finish(page, "Both added.");
    expect(toolSections(live), "one tool section for one piece of work").toBe(
      1,
    );
    // A todo card renders the todo the call returned: it opens that todo.
    for (const title of ["rt-1", "rt-2"]) {
      expect(botLinesReading(live, title)).toBe(1);
      await expect(page.getByRole("button", { name: title })).toHaveCount(1);
    }
    await page.getByRole("button", { name: "rt-2" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "rt-2" }),
      "the card carries the created todo",
    ).toBeVisible();
  });

  // Bugs 26 and 27: a reply naming a file showed its sandbox path, linked the wrong
  // host, and its streamed text was cut back to "Saved" when the path resolved.
  test("a reply naming a saved file shows the file linked to the chat, never its sandbox path", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      "save it [[pace:40]] [[say:Saved it to /workspace/sessions/s1/artifacts/notes.txt for you.]]",
    );
    const live = await finish(page, "Saved it to notes.txt for you.");
    expect(
      live.filter((i) => i.role === "bot" && i.text.includes("/workspace/")),
      "no sandbox path on screen",
    ).toEqual([]);
    await expect(
      page
        .locator('[data-screen-item-kind="reply"]')
        .getByRole("link", { name: "notes.txt" }),
      "the file opens its conversation in the web app",
    ).toHaveAttribute(
      "href",
      `${WEB_BASE_URL}/c/${conversationIdOf(page.url())}`,
    );
    // The sim stack has no file storage: the conversation still goes on.
    await sendMessage(page, "and next? [[say:Next one.]]");
    await finish(page, "Next one.");
  });

  // Each message joining an uncommitted attempt restarts it, and every reply but the last
  // holds, so the third arrives before anything commits: one reply answers all three, under
  // the last. A message the step drops leaves no reply.
  test("three messages sent in a burst are answered by one reply under the last", async ({
    page,
  }) => {
    await openNewChat(page);
    const words = ["first", "second", "third"];
    await sendAndOpen(page, `${words[0]} [[wait:3000]] [[say:Reply one.]]`);
    await sendMessage(page, `${words[1]} [[wait:3000]] [[say:Reply two.]]`);
    await sendMessage(page, `${words[2]} [[say:Reply three.]]`);
    const live = await finish(page, "Reply three.");
    expectUserOrder(live, words);
    expect(roles(live), "one reply answers the burst, under it").toEqual([
      "user",
      "user",
      "user",
      "bot",
    ]);
    expect(live[3].text).toBe("Reply three.");
  });

  test("a side question during running work is answered while the work keeps its one section", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, heldWork("sq", "Work done."));
    await untilBotLine(page, "sq-1");
    await sendMessage(page, "quick question [[say:Side answer.]]");
    await untilBotLine(page, "Side answer.");
    expect(
      botLinesReading(await currentScreen(page), "sq-2"),
      "the answer came while the work still ran",
    ).toBe(0);
    await expect(loadingRow(page)).toBeVisible();
    const live = await finish(page, "Work done.");
    expectUserOrder(live, ["work", "quick question"]);
    expect(toolSections(live), "the work is one section").toBe(1);
    expect(botLinesReading(live, "sq-1")).toBe(1);
    expect(botLinesReading(live, "sq-2")).toBe(1);
    // The result sits below the side question, so it quotes the message that asked for the
    // work; the side answer sits right under its own question and quotes nothing.
    const replyReading = (line: string) =>
      live.find((i) => i.kind === "reply" && i.text.split("\n").includes(line))
        ?.text ?? "";
    expect(replyReading("Work done."), "the result quotes its ask").toMatch(
      /^You\nwork /m,
    );
    expect(
      replyReading("Side answer."),
      "the side answer quotes nothing",
    ).not.toMatch(/^You$/m);
  });

  test("stopping mid-work shows Stopped and nothing on screen vanishes", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, heldWork("st", "Never said."));
    await untilBotLine(page, "st-1");
    // The front door acknowledges with the scripted text at hand-off; nothing may follow the stop.
    const acknowledged = botLinesReading(
      await currentScreen(page),
      "Never said.",
    );
    await page.getByRole("button", { name: "Stop generation" }).click();
    await expect(page.getByText("Stopped").first()).toBeVisible({
      timeout: TURN_MS,
    });
    await expect(loadingRow(page)).toHaveCount(0, { timeout: TURN_MS });
    const live = await settledScreen(page, "st-1", TURN_MS);
    await expectScreenOnlyGrew(page);
    expect(
      botLinesReading(live, "st-2"),
      "the stopped work did not continue",
    ).toBe(0);
    expect(
      botLinesReading(live, "Never said."),
      "no reply after the stop",
    ).toBe(acknowledged);
    await expectReloadMatches(page, live, TURN_MS);
  });

  test("a reload mid-reply resumes the same items in the same order", async ({
    page,
  }) => {
    await openNewChat(page);
    const words = Array.from({ length: 40 }, (_, i) => `w${i}`).join(" ");
    await sendAndOpen(page, `stream it [[pace:150]] [[say:${words} end.]]`);
    await expect
      .poll(async () => (await currentScreen(page)).length, {
        timeout: TURN_MS,
      })
      .toBeGreaterThan(1);
    const before = await currentScreen(page);
    await expectScreenOnlyGrew(page);
    await page.reload();
    const live = await settledScreen(page, `${words} end.`, TURN_MS);
    await expectScreenOnlyGrew(page);
    expect(live.map((i) => i.id).slice(0, before.length)).toEqual(
      before.map((i) => i.id),
    );
    expect(roles(live)).toEqual(["user", "bot"]);
    await expectReloadMatches(page, live, TURN_MS);
  });

  test("two tabs on one chat show the same items in the same order, live", async ({
    browser,
  }) => {
    const first = await (await browser.newContext()).newPage();
    const second = await (await browser.newContext()).newPage();
    await openNewChat(first);
    await sendAndOpen(first, "hello [[say:First turn.]]");
    await settledScreen(first, "First turn.", TURN_MS);
    await recordScreen(second);
    await second.goto(first.url());
    await settledScreen(second, "First turn.", TURN_MS);

    await sendMessage(first, `more ${todo("tt-1")} [[say:Second turn.]]`);
    const onFirst = await settledScreen(first, "Second turn.", TURN_MS);
    await expect
      .poll(async () => currentScreen(second), { timeout: TURN_MS })
      .toEqual(onFirst);
    await expectScreenOnlyGrew(first);
    await expectScreenOnlyGrew(second);
  });

  test("a failed reply keeps its streamed text and cards in place", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      `${todo("ff-1")} [[say:Partial progress.]] [[fail:provider dropped the stream]]`,
    );
    await expect(page.getByText(MODEL_ERROR_LINE)).toBeVisible({
      timeout: TURN_MS,
    });
    const live = await finish(page, "Partial progress.");
    expect(botLinesReading(live, "ff-1")).toBe(1);
    // The model call is retried after the break: each attempt streams the same words, shown once.
    expect(botLinesReading(live, "Partial progress.")).toBe(1);
  });

  test("Retry on a failed reply resends that reply's message, not an earlier one", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, "one [[say:First fine.]]");
    await settledScreen(page, "First fine.", TURN_MS);
    await sendMessage(
      page,
      "two [[say:Second partial.]] [[fail:provider dropped the stream]]",
    );
    // Every user message carries its own Retry; this is the failed reply's.
    const failed = page
      .getByText(MODEL_ERROR_LINE)
      .locator("..")
      .getByRole("button", { name: "Retry" });
    await expect(failed).toBeVisible({ timeout: TURN_MS });
    const before = await currentScreen(page);
    const attemptsBefore = botLinesReading(before, "Second partial.");
    await failed.click();
    await expect
      .poll(
        async () =>
          botLinesReading(await currentScreen(page), "Second partial."),
        {
          timeout: TURN_MS,
          message: "the retry re-ran the failed message",
        },
      )
      .toBeGreaterThan(attemptsBefore);
    const live = await settledScreen(page, "Second partial.", TURN_MS);
    await expectScreenOnlyGrew(page);
    expect(
      botLinesReading(live, "First fine."),
      "the earlier message was not resent",
    ).toBe(1);
    expect(live.filter((i) => i.role === "user").map((i) => i.text)).toEqual(
      before.filter((i) => i.role === "user").map((i) => i.text),
    );
  });

  test("the loading line stays up for the whole time work streams", async ({
    page,
  }) => {
    await openNewChat(page);
    const watch = watchConversation(page, ["ld-1", "ld-2"]);
    await sendAndOpen(page, heldWork("ld", "Loaded."));
    await untilBotLine(page, "ld-2");
    await settledScreen(page, "Loaded.", TURN_MS);
    const samples = await watch.stop();
    // Work streams from its first card until its last shows; the turn may end in that same reading.
    expect(
      loadingGaps(
        samples,
        firstShownAt(samples, "ld-1"),
        firstShownAt(samples, "ld-2") - 1,
      ),
      "no moment of running work without the loading line",
    ).toEqual([]);
    expect(
      longestBlindWorkMs(samples),
      "nothing grows while the line is hidden",
    ).toBeLessThan(1_000);
  });

  test("a pending send becomes the server's user item in place, without moving", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, "first [[say:Got the first.]]");
    await settledScreen(page, "Got the first.", TURN_MS);
    await sendMessage(page, "second [[say:Got the second.]]");
    await settledScreen(page, "Got the second.", TURN_MS);
    const frames = await timeline(page);
    const positions = frames.flatMap((frame) => {
      const at = frame.items.findIndex(
        (i) => i.role === "user" && i.text.startsWith("second"),
      );
      return at < 0 ? [] : [`${at}:${frame.items[at].id}`];
    });
    expect(positions.length, "the send showed at once").toBeGreaterThan(0);
    expect(
      new Set(positions),
      "one id at one position, pending to delivered",
    ).toEqual(new Set([positions[0]]));
    const live = await finish(page, "Got the second.");
    expect(
      positions[0].split(":")[1],
      "the server item kept the pending send's id",
    ).toBe(
      live.find((i) => i.role === "user" && i.text.startsWith("second"))?.id,
    );
  });

  test("a reply, then work, then a reply render in the server's order", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, "say hi [[say:Hi first.]]");
    await settledScreen(page, "Hi first.", TURN_MS);
    await sendMessage(page, `now work ${todo("ord-1")} [[say:Work reply.]]`);
    await settledScreen(page, "ord-1", TURN_MS);
    await sendMessage(page, "and again [[say:Last reply.]]");
    const live = await finish(page, "Last reply.");
    const kinds = live.map((i) => i.kind);
    const work = kinds.indexOf("work");
    expect(work, "the work is on screen").toBeGreaterThan(0);
    expect(kinds.slice(0, work)).toContain("reply");
    expect(kinds.slice(work + 1)).toContain("reply");
  });
});

test.describe("screen over time — approvals", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the sim stack (`mise dev --sim`, E2E_SIM=1).",
  );
  test.setTimeout(5 * TURN_MS);
  test.beforeEach(async () => askBefore(["create_todo"]));
  test.afterEach(async () => askBefore([]));

  /** Ask to approve a todo; `before` scripts what the work does after the ask and before `reply`. */
  async function askForApproval(
    page: Page,
    title: string,
    reply: string,
    before = "",
  ) {
    await openNewChat(page);
    await sendAndOpen(page, `${todo(title)} ${before}[[say:${reply}]]`);
    const card = page.getByText(APPROVAL_COPY.needsApproval).first();
    await expect(card).toBeVisible({ timeout: TURN_MS });
    await expectScreenOnlyGrew(page);
  }

  test("approving runs the call in the same work section", async ({ page }) => {
    await askForApproval(page, "ap-1", "Approved and added.");
    await page
      .getByRole("button", { name: APPROVAL_COPY.approve, exact: true })
      .click();
    const live = await finish(page, "Approved and added.");
    expect(
      toolSections(live),
      "the approved call joins its work, not a new section",
    ).toBe(1);
    expect(
      botLinesReading(live, APPROVAL_COPY.needsApproval),
      "the card resolved",
    ).toBe(0);
    await expectTodos(page, ["ap-1"]);
  });

  // Conversation 741603c7: Approve tapped while the run still wound down read "please approve" after.
  test("approving before the work's run ends is never followed by a stale ask", async ({
    page,
  }) => {
    const ask = "Approve fa-1 in the card.";
    const done = "Added fa-1.";
    const finishAsking = `[[tool:finish_task {"result":"${ask}","outcome":"ask"}]]`;
    // The run holds its last step, so the tap lands before it ends asking.
    await askForApproval(
      page,
      "fa-1",
      done,
      `[[wait:${HOLD_MS}]] ${finishAsking} `,
    );
    await page
      .getByRole("button", { name: APPROVAL_COPY.approve, exact: true })
      .click();
    const live = await finish(page, done);
    expect(botLinesReading(live, ask), "the decided ask is never said").toBe(0);
    expect(botLinesReading(live, done), "the work is reported once").toBe(1);
    expect(toolSections(live)).toBe(1);
    await expectTodos(page, ["fa-1"]);
  });

  // A plain no is final: the card resolves and no run starts to report the skip (7f9de0cdcb).
  test("denying leaves the call unrun, the card resolved and nothing said after", async ({
    page,
  }) => {
    await askForApproval(page, "dn-1", "Not added.");
    await page
      .getByRole("button", { name: APPROVAL_COPY.deny, exact: true })
      .click();
    await expect(page.getByText(APPROVAL_COPY.needsApproval)).toHaveCount(0, {
      timeout: TURN_MS,
    });
    await expect(page.getByTestId("chat-loading-row")).toHaveCount(0, {
      timeout: TURN_MS,
    });
    const live = await currentScreen(page);
    await expectScreenOnlyGrew(page);
    expect(
      botLinesReading(live, "Not added."),
      "no run reports a plain no",
    ).toBe(0);
    expect(toolSections(live)).toBeLessThanOrEqual(1);
    await expectReloadMatches(page, live, TURN_MS);
    await expectTodos(page, [], ["dn-1"]);
  });

  test("an approval nobody answers expires on screen without a reload", async ({
    page,
  }) => {
    test.setTimeout(SWEEP_MS + 3 * TURN_MS);
    await askForApproval(page, "ex-1", "Expired.");
    backdateApproval(conversationIdOf(page.url()));
    await expect(page.getByText(APPROVAL_COPY.needsApproval)).toHaveCount(0, {
      timeout: SWEEP_MS,
    });
    await expect(page.getByText("Expired").first()).toBeVisible();
    const live = await settledScreen(page, "Expired.", TURN_MS);
    await expectScreenOnlyGrew(page);
    await expectReloadMatches(page, live, TURN_MS);
  });

  test("a decision in one tab resolves the card in the other", async ({
    browser,
  }) => {
    const first = await (await browser.newContext()).newPage();
    const second = await (await browser.newContext()).newPage();
    await askForApproval(first, "tw-1", "Decided elsewhere.");
    await recordScreen(second);
    await second.goto(first.url());
    await expect(
      second.getByText(APPROVAL_COPY.needsApproval).first(),
    ).toBeVisible({
      timeout: TURN_MS,
    });
    await first
      .getByRole("button", { name: APPROVAL_COPY.approve, exact: true })
      .click();
    await expect(second.getByText(APPROVAL_COPY.needsApproval)).toHaveCount(0, {
      timeout: TURN_MS,
    });
    const onFirst = await settledScreen(first, "Decided elsewhere.", TURN_MS);
    await expect
      .poll(async () => currentScreen(second), { timeout: TURN_MS })
      .toEqual(onFirst);
    await expectScreenOnlyGrew(first);
    await expectScreenOnlyGrew(second);
  });
});
