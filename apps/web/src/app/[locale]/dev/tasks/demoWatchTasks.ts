import { addDays, nextFriday, setHours, startOfHour, subHours } from "date-fns";

import type { Task, TaskWatch } from "./taskModel";
import { DEADLINE_HOUR, onWatch, WATCH_EXPIRY_DAYS } from "./watchModel";
import { onEvent, WEBHOOK_TRIGGER } from "./whenModel";

/** Illustrative watches and a webhook task for the design demo, one per state a watch can be in. */

const base = {
  assignee: "gaia",
  integrations: [],
  checklist: [],
  runs: [],
  notify: true,
  priority: "none",
} satisfies Partial<Task>;

const hoursAgo = (hours: number) => subHours(new Date(), hours).toISOString();

/** Set up some days ago, so it ends 90 days after that. */
const expiresFrom = (daysAgo: number) =>
  addDays(new Date(), WATCH_EXPIRY_DAYS - daysAgo).toISOString();

/** The fields every demo watch shares, with its own on top. */
const watch = (
  own: Omit<TaskWatch, "alerts" | "confirmTwice" | "expiresAt"> &
    Partial<TaskWatch>,
): TaskWatch => ({
  alerts: 0,
  confirmTwice: false,
  expiresAt: expiresFrom(4),
  ...own,
});

export const WATCH_TASKS: Task[] = [
  {
    ...base,
    id: "billy-bookcase",
    title: "Tell me when the Billy bookcase drops under $50",
    state: "waiting",
    when: onWatch(
      watch({
        sentence: "Tell me when the Billy bookcase drops under $50",
        kind: "threshold",
        source: { rung: "page", site: "ikea.com", label: "Billy bookcase" },
        condition: { direction: "below", value: 50, unit: "$" },
        reading: { value: "$59", at: hoursAgo(0.2) },
        everyMinutes: 60,
        confirmTwice: true,
      }),
      { afterRuns: 1 },
    ),
  },
  {
    ...base,
    id: "hn-mentions",
    title: "Posts about GAIA on Hacker News",
    state: "waiting",
    when: onWatch(
      watch({
        sentence: "Tell me whenever someone posts about GAIA on Hacker News",
        kind: "new_items",
        source: {
          rung: "api",
          site: "news.ycombinator.com",
          label: "Hacker News",
        },
        condition: { items: "New posts about GAIA" },
        reading: { value: "2 new this week", at: hoursAgo(0.1) },
        everyMinutes: 15,
        alerts: 2,
        expiresAt: expiresFrom(9),
      }),
    ),
    runs: [
      {
        id: "hn2",
        at: "Thu, 4:12 PM",
        outcome: "success",
        summary: 'Told you about "Show HN: GAIA, a proactive assistant"',
        duration: "6s",
        trigger: "watch",
        trace: [],
      },
    ],
  },
  {
    ...base,
    id: "site-down",
    title: "Tell me if northwind.co goes down",
    state: "waiting",
    when: onWatch(
      watch({
        sentence: "Tell me if northwind.co goes down",
        kind: "uptime",
        source: { rung: "page", site: "northwind.co", label: "northwind.co" },
        condition: {},
        reading: { value: "Up", at: hoursAgo(0.01) },
        everyMinutes: 1,
        confirmTwice: true,
        expiresAt: expiresFrom(30),
      }),
    ),
  },
  {
    ...base,
    id: "kenji-nda",
    title: "Nudge me if Kenji hasn't sent the NDA back by Friday",
    state: "waiting",
    source: { app: "gmail", label: "Email thread" },
    when: onWatch(
      watch({
        sentence: "Nudge me if Kenji hasn't sent the NDA back by Friday",
        kind: "reply_by",
        source: { rung: "connector", app: "gmail", label: "Kenji's thread" },
        condition: {
          from: "Kenji",
          deadline: setHours(
            startOfHour(nextFriday(new Date())),
            DEADLINE_HOUR,
          ).toISOString(),
        },
        reading: { value: "No reply yet", at: hoursAgo(0.3) },
        everyMinutes: 15,
      }),
      { afterRuns: 1 },
    ),
  },
  {
    ...base,
    id: "steam-sale",
    title: "Tell me when the Steam winter sale starts",
    state: "waiting",
    when: onWatch(
      watch({
        sentence: "Tell me when the Steam winter sale starts",
        kind: "open",
        source: { rung: "agent", label: "The Steam winter sale" },
        condition: {},
        reading: { value: "Not announced yet", at: hoursAgo(5) },
        everyMinutes: 1440,
      }),
      { afterRuns: 1 },
    ),
  },
  {
    ...base,
    id: "pr-merged",
    title: "Tell me when PR #482 is merged",
    state: "waiting",
    when: onWatch(
      watch({
        sentence: "Tell me when PR #482 is merged",
        kind: "state",
        source: { rung: "connector", app: "github", label: "PR #482" },
        condition: {
          target: "Merged",
          states: ["Merged", "Closed", "Any change"],
          finalStates: ["Merged", "Closed"],
        },
        reading: { value: "Open, 2 approvals", at: hoursAgo(20) },
        everyMinutes: 15,
        blind: { reason: "signed_out", since: hoursAgo(18) },
      }),
      { afterRuns: 1 },
    ),
  },
  {
    ...base,
    id: "coldplay",
    title: "Tell me when Coldplay tickets for Mumbai go on sale",
    state: "paused",
    pauseReason: "watch_blind",
    when: onWatch(
      watch({
        sentence: "Tell me when Coldplay tickets for Mumbai go on sale",
        kind: "state",
        source: {
          rung: "browser",
          site: "district.in",
          label: "Coldplay, Mumbai",
        },
        condition: {
          target: "On sale",
          states: ["On sale", "Any change"],
          finalStates: ["On sale", "Sold out"],
        },
        reading: { value: "Coming soon", at: hoursAgo(76) },
        everyMinutes: 30,
        confirmTwice: true,
        blind: { reason: "blocked", since: hoursAgo(74) },
      }),
      { afterRuns: 1 },
    ),
  },
  {
    ...base,
    id: "headphones",
    title: "Tell me when the Sony XM6 drops under $300",
    state: "done",
    doneToday: true,
    when: onWatch(
      watch({
        sentence: "Tell me when the Sony XM6 drops under $300",
        kind: "threshold",
        source: { rung: "page", site: "bestbuy.com", label: "Sony XM6" },
        condition: { direction: "below", value: 300, unit: "$" },
        reading: { value: "$279", at: hoursAgo(3) },
        everyMinutes: 60,
        confirmTwice: true,
        alerts: 1,
        ended: {
          why: "It hit $279 this morning. GAIA told you, and the watch ended.",
          at: hoursAgo(3),
        },
      }),
      { afterRuns: 1 },
    ),
    runs: [
      {
        id: "xm1",
        at: "Today, 8:05 AM",
        outcome: "success",
        summary: "Told you the Sony XM6 is $279 at Best Buy",
        duration: "4s",
        trigger: "watch",
        trace: [],
      },
    ],
  },
  {
    ...base,
    id: "stripe-welcome",
    title: "Welcome new Stripe customers",
    state: "standing",
    instructions:
      "When someone subscribes, send them a short welcome from me with the onboarding guide, and add them to the Customers sheet.",
    integrations: ["gmail", "googlesheets"],
    icon: { name: "Mail01Icon", color: "#a78bfa" },
    when: onEvent(WEBHOOK_TRIGGER, "It's a new subscription", undefined, {
      id: "c41f9a07d2b84e6a91f3e0b5",
      signing: "stripe",
      secret: "whsec_demo7c2f19e04b6a8d3e5f1c",
      lastReceived: hoursAgo(2),
    }),
    runs: [
      {
        id: "sw1",
        at: "Today, 9:14 AM",
        outcome: "success",
        summary: "Welcomed Dana Ortiz and added her to the sheet",
        duration: "14s",
        trigger: "webhook",
        trace: [
          { app: "gmail", text: "Sent the welcome to dana@lumen.studio" },
          { app: "googlesheets", text: "Added a row to Customers" },
        ],
      },
    ],
  },
];
