import { HtmlLocator, HtmlScene } from "@effect/ui/html/testing";
import { Locator, Story } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import {
  FocusSearchInput,
  PinsMessage,
  PinsPageNoDeps,
} from "../src/pages/pins/PinsPage";

const report = {
  conversation_id: "conv-1",
  message: {
    message_id: "msg-1",
    date: "2026-11-27T10:00:00.000Z",
    response: "The quarterly report is ready for review.",
  },
};

const launch = {
  conversation_id: "conv-2",
  message: {
    message_id: "msg-2",
    date: null,
    response: "Draft the launch plan before Friday.",
  },
};

const noMessageId = {
  conversation_id: "conv-3",
  message: { message_id: null, date: null, response: "No id on this one." },
};

it.effect("seeded pins render one card per message", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(PinsPageNoDeps, {});
    scene.given({ search: "" }, { pins: [report, launch] });
    scene.expectMount(FocusSearchInput());

    scene
      .expect(Locator.text("The quarterly report is ready for review."))
      .toExist();
    scene
      .expect(Locator.text("Draft the launch plan before Friday."))
      .toExist();
    scene.expect(HtmlLocator.role("link")).toHaveCount(2);
    scene.expect(Locator.attr("href", "/c/conv-1?messageId=msg-1")).toExist();
    scene.expect(Locator.attr("href", "/c/conv-2?messageId=msg-2")).toExist();
  }),
);

it.effect("a message without an id links to its conversation alone", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(PinsPageNoDeps, {});
    scene.given({ search: "" }, { pins: [noMessageId] });
    scene.expectMount(FocusSearchInput());

    scene.expect(Locator.attr("href", "/c/conv-3")).toExist();
  }),
);

it.effect("typing in the search field filters the cards", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(PinsPageNoDeps, {});
    scene.given({ search: "" }, { pins: [report, launch] });
    scene.expectMount(FocusSearchInput());

    scene.type(
      HtmlLocator.placeholder("Enter a message to filter pins"),
      "launch",
    );

    scene
      .expect(Locator.text("Draft the launch plan before Friday."))
      .toExist();
    scene
      .expect(Locator.text("The quarterly report is ready for review."))
      .toBeAbsent();
  }),
);

it.effect("no pins renders the empty state", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(PinsPageNoDeps, {});
    scene.given({ search: "" }, { pins: [] });
    scene.expectMount(FocusSearchInput());

    scene.expect(Locator.text("No pinned messages yet")).toExist();
    scene
      .expect(
        Locator.text(
          "PinIcon important messages during conversations to find them easily later",
        ),
      )
      .toExist();
  }),
);

it.effect(
  "a search that matches nothing renders the filtered empty state",
  () =>
    Effect.gen(function* () {
      const scene = yield* HtmlScene.make(PinsPageNoDeps, {});
      scene.given({ search: "" }, { pins: [report, launch] });
      scene.expectMount(FocusSearchInput());

      scene.type(
        HtmlLocator.placeholder("Enter a message to filter pins"),
        "none of these",
      );

      scene.expect(Locator.text("No pins match your search")).toExist();
      scene
        .expect(
          Locator.text("Try adjusting your search terms or clear the filter"),
        )
        .toExist();
    }),
);

it.effect("the clear button empties the search query", () =>
  Effect.gen(function* () {
    const story = yield* Story.make(PinsPageNoDeps, {});
    story.given({ search: "launch" }, { pins: [] });

    story.send(PinsMessage.PressedClearButton());

    assert.deepStrictEqual(story.model, { search: "" });
  }),
);
