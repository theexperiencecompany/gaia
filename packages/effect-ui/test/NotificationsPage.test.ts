import { HtmlLocator, HtmlScene } from "@effect/ui/html/testing";
import { Locator, Story } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import {
  MarkNotificationRead,
  NotificationsMessage,
  NotificationsPageNoDeps,
} from "../src/pages/notifications/NotificationsPage";

const notification = {
  id: "notification-1",
  status: "delivered" as const,
  created_at: new Date().toISOString(),
  content: {
    title: "Daily briefing",
    body: "Your day starts in 10 minutes.",
  },
  channels: [{ channel_type: "inapp" }],
};

it.effect("a delivered notification renders its title and time group", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(NotificationsPageNoDeps, {});
    scene.given({}, { notifications: [notification] });

    scene.expect(Locator.text("Daily briefing")).toExist();
    scene.expect(Locator.text("Today")).toExist();
    scene.expect(Locator.text("Your day starts in 10 minutes.")).toExist();
  }),
);

it.effect("an empty page shows the caught-up state", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(NotificationsPageNoDeps, {});
    scene.given({}, { notifications: [] });

    scene.expect(Locator.text("No unread notifications")).toExist();
    scene
      .expect(Locator.text("All caught up! You're up to date with everything."))
      .toExist();
  }),
);

it.effect("the mark-as-read button issues MarkNotificationRead", () =>
  Effect.gen(function* () {
    const story = yield* Story.make(NotificationsPageNoDeps, {});
    story.given({}, { notifications: [notification] });

    story.send(
      NotificationsMessage.RequestedMarkAsRead({ id: notification.id }),
    );
    story.expectExact(MarkNotificationRead);
    story.resolve(
      MarkNotificationRead,
      NotificationsMessage.SucceededMarkNotificationRead(),
    );

    assert.deepStrictEqual(story.model, {});
  }),
);

it.effect("clicking the mark-as-read button issues MarkNotificationRead", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(NotificationsPageNoDeps, {});
    scene.given({}, { notifications: [notification] });

    scene.click(HtmlLocator.role("button", { name: "Mark as read" }));
    scene.expectExact(MarkNotificationRead);
    scene.resolve(
      MarkNotificationRead,
      NotificationsMessage.SucceededMarkNotificationRead(),
    );
  }),
);
