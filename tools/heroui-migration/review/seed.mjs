#!/usr/bin/env node
/**
 * The one deterministic dataset both builds are reviewed against.
 *
 *   node review/seed.mjs --api http://localhost:8100/api/v1 --out ~/v3review/out --api-tree ~/v3review/before
 *
 * Resets and re-creates two users through the real API (dev router + the same
 * endpoints the web app calls): review@gaia.local, fully onboarded with Pro and
 * every surface populated, and onboarding@gaia.local, who has not onboarded.
 * Notifications have no create endpoint, so seed_notifications.py writes them
 * through the API's own notification storage. Every request fails loud.
 *
 * Writes <out>/seed-state.json: the ids the route inventory binds dynamic
 * segments to, and seededAt, which the capture clock is pinned relative to.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { API_BASE, DEFAULT_OUT, ONBOARDING_USER, REVIEW_USER, TIMEZONE } from "./config.mjs";
import { EXTRA_TOOL_FIXTURES } from "./extra-tool-fixtures.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..", "..");
const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
const API = arg("api", API_BASE).replace(/\/+$/, "");
const OUT = resolve(arg("out", DEFAULT_OUT));
const API_TREE = resolve(arg("api-tree", REPO));


const { TOOL_FIXTURES } = await import(join(API_TREE, "libs/shared/ts/src/chat/fixtures.ts"));
const fixtureByName = new Map(
  [...TOOL_FIXTURES, ...EXTRA_TOOL_FIXTURES].map((f) => [f.toolName, f]),
);

async function call(method, path, { body, user = REVIEW_USER, ok = [200, 201, 204] } = {}) {
  const res = await fetch(API + path, {
    method,
    headers: { "content-type": "application/json", "X-Dev-User": user },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (!ok.includes(res.status)) {
    throw new Error(`${method} ${path} -> ${res.status}: ${text.slice(0, 600)}`);
  }
  return text ? JSON.parse(text) : null;
}
// The dev router authenticates nobody; X-Dev-User on it would only 401 before the user exists.
const dev = (method, path, body, ok) =>
  fetch(API + "/dev" + path, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(async (res) => {
    const text = await res.text();
    if (!(ok ?? [200, 201]).includes(res.status)) throw new Error(`dev ${method} ${path} -> ${res.status}: ${text.slice(0, 400)}`);
    return text ? JSON.parse(text) : null;
  });

/** Deterministic v4-shaped UUID from a small integer, so /c/<id> URLs are stable across reseeds. */
const uuid = (n) => `5eed0000-0000-4000-8000-${String(n).padStart(12, "0")}`;

const seededAt = new Date();
seededAt.setUTCSeconds(0, 0);
const at = (minutesAgo) => new Date(seededAt.getTime() - minutesAgo * 60_000).toISOString();
const inDays = (d, hour = 17) => {
  const t = new Date(seededAt);
  t.setUTCDate(t.getUTCDate() + d);
  t.setUTCHours(hour, 0, 0, 0);
  return t.toISOString();
};

// One conversation per area, so each /c/<id> route reviews a coherent set of cards.
const CHAT_GROUPS = [
  { key: "search", title: "Research and search", tools: ["weather_data", "search_results", "deep_research_results", "people_search_data", "contacts_data"] },
  { key: "mail", title: "Inbox triage", tools: ["email_fetch_data", "email_thread_data", "email_compose_data", "email_sent_data"] },
  { key: "calendar", title: "Planning the week", tools: ["calendar_options", "calendar_fetch_data", "calendar_list_fetch_data", "calendar_edit_options", "calendar_delete_options"] },
  { key: "tasks", title: "Todos and workflows", tools: ["todo_data", "todo_progress", "workflow_draft", "workflow_created", "notification_data", "send_notification_data", "support_ticket_data"] },
  { key: "content", title: "Docs, code and social", tools: ["google_docs_data", "code_data", "artifact_data", "twitter_search_data", "twitter_user_data", "reddit_data"] },
  { key: "system", title: "Integrations and approvals", tools: ["integration_connection_required", "integration_list_data", "connection_status_data", "connect_options", "approval_request", "device_onboarding_required", "device_approval_required", "rate_limit_data", "memory_data", "mcp_app", "tool_calls_data", "chart_data", "screenshot_data", "browser_task_data"] },
];

const MARKDOWN_REPLY = [
  "## Your week at a glance",
  "",
  "Here is what matters most, in order:",
  "",
  "1. **Ship the HeroUI v3 review** before Friday.",
  "2. Reply to Priya about the design review.",
  "3. Book flights for the offsite.",
  "",
  "| Day | Focus | Meetings |",
  "| --- | --- | --- |",
  "| Mon | Deep work | 1 |",
  "| Tue | Reviews | 3 |",
  "| Wed | Planning | 2 |",
  "",
  "> Tip: block two hours on Monday morning for the review.",
  "",
  "```ts",
  'const focus = ["review", "reply", "book"];',
  "console.log(focus.join(\" -> \"));",
  "```",
  "",
  "Want me to add these as todos? You can also [open your calendar](/calendar).",
].join("\n");

function chatMessages(group, base) {
  const messages = [];
  let minute = 600;
  group.tools.forEach((toolName, i) => {
    const fixture = fixtureByName.get(toolName);
    if (!fixture) throw new Error(`no fixture for tool card ${toolName}`);
    messages.push({
      type: "user",
      response: `Show me the ${fixture.label.toLowerCase()}.`,
      date: at(minute--),
      message_id: `${base}-u${i}`,
    });
    messages.push({
      type: "bot",
      response: `Here is the ${fixture.label.toLowerCase()}.`,
      date: at(minute--),
      message_id: `${base}-b${i}`,
      tool_data: [{ tool_name: toolName, data: fixture.data, timestamp: at(minute) }],
    });
  });
  return messages;
}

/** Delete a user and what dev teardown leaves behind: workflows (a Pro-only read, so only for the Pro user). */
async function resetUser(email, { ownsWorkflows }) {
  const exists = await fetch(`${API}/user/me`, { headers: { "X-Dev-User": email } });
  if (![200, 401].includes(exists.status)) throw new Error(`GET /user/me as ${email} -> ${exists.status}`);
  if (exists.status === 200 && ownsWorkflows) {
    const { workflows } = await call("GET", "/workflows", { user: email });
    for (const w of workflows) await call("DELETE", `/workflows/${w.id}`, { user: email });
  }
  await dev("DELETE", `/users/${encodeURIComponent(email)}`, undefined, [200, 404]);
}

async function seedReviewUser() {
  await resetUser(REVIEW_USER, { ownsWorkflows: true });
  const user = await dev("POST", "/users", { email: REVIEW_USER, name: "Alex Morgan" });
  await dev("POST", "/seed", { email: REVIEW_USER, todos: 0, conversations: 0, platform_links: ["telegram", "discord"], pro: true });
  const tz = await fetch(`${API}/user/timezone`, {
    method: "PATCH",
    headers: { "X-Dev-User": REVIEW_USER },
    body: new URLSearchParams({ timezone: TIMEZONE }),
  });
  if (!tz.ok) throw new Error(`PATCH /user/timezone -> ${tz.status}: ${await tz.text()}`);

  const projects = {};
  for (const [key, name, color] of [
    ["work", "Work", "#00bbff"],
    ["personal", "Personal", "#22c55e"],
    ["offsite", "Team offsite", "#f59e0b"],
  ]) {
    projects[key] = (await call("POST", "/projects", { body: { name, color, description: `${name} tasks` } })).id;
  }

  const TODOS = [
    { title: "Ship the HeroUI v3 review", project: "work", priority: "high", due: 0, labels: ["design", "urgent"], subtasks: ["Capture v2", "Capture v3", "Triage diffs"] },
    { title: "Reply to Priya about the design review", project: "work", priority: "medium", due: 0, labels: ["email"] },
    { title: "Prepare quarterly roadmap", project: "work", priority: "medium", due: 3, labels: ["planning"], description: "Draft the Q1 roadmap and share with the team." },
    { title: "Fix flaky login test", project: "work", priority: "low", due: -2, labels: ["bug"] },
    { title: "Book flights for the offsite", project: "offsite", priority: "high", due: 1, labels: ["travel"] },
    { title: "Shortlist venues", project: "offsite", priority: "none", due: 6, labels: ["travel", "planning"], subtasks: ["Goa", "Udaipur"] },
    { title: "Renew passport", project: "personal", priority: "high", due: 10, labels: ["admin"] },
    { title: "Buy groceries", project: "personal", priority: "none", due: 0, labels: [] },
    { title: "Call the dentist", project: "personal", priority: "low", due: 2, labels: ["health"] },
    { title: "Read the new design system doc", project: null, priority: "none", due: null, labels: ["design"] },
    { title: "Send weekly status email", project: "work", priority: "medium", due: -1, labels: ["email"], completed: true },
    { title: "Archive old Figma files", project: "work", priority: "low", due: null, labels: ["design"], completed: true },
  ];
  const todos = {};
  for (const t of TODOS) {
    const created = await call("POST", "/todos", {
      body: {
        title: t.title,
        description: t.description,
        labels: t.labels,
        priority: t.priority,
        project_id: t.project ? projects[t.project] : undefined,
        due_date: t.due === null ? undefined : inDays(t.due),
        due_date_timezone: t.due === null ? undefined : TIMEZONE,
        subtasks: (t.subtasks ?? []).map((title, i) => ({ id: `st-${i}`, title, completed: i === 0 })),
      },
    });
    if (t.completed) await call("PUT", `/todos/${created.id}`, { body: { completed: true } });
    todos[t.title] = created.id;
  }

  const conversations = {};
  let n = 1;
  for (const group of CHAT_GROUPS) {
    const id = uuid(n++);
    await call("POST", "/conversations", { body: { conversation_id: id, description: group.title } });
    await call("PUT", `/conversations/${id}/messages`, { body: { conversation_id: id, messages: chatMessages(group, `seed-${group.key}`) } });
    conversations[group.key] = id;
  }
  const textId = uuid(n++);
  await call("POST", "/conversations", { body: { conversation_id: textId, description: "Weekly plan" } });
  await call("PUT", `/conversations/${textId}/messages`, {
    body: {
      conversation_id: textId,
      messages: [
        { type: "user", response: "What should I focus on this week?", date: at(30), message_id: "seed-text-u0" },
        { type: "bot", response: MARKDOWN_REPLY, date: at(29), message_id: "seed-text-b0", follow_up_actions: ["Add these as todos", "Block focus time"] },
      ],
    },
  });
  conversations.text = textId;
  await call("PUT", `/conversations/${textId}/star`, { body: { starred: true } });
  await call("PUT", `/conversations/${textId}/messages/seed-text-b0/pin`, { body: { pinned: true } });

  const workflows = {};
  const STEPS = [
    { title: "Fetch unread email", category: "gmail", description: "Read the unread messages from the last day." },
    { title: "Summarise", category: "general", description: "Summarise each thread in one line." },
    { title: "Send the digest", category: "notifications", description: "Send the summary to me on Telegram." },
  ];
  const WORKFLOWS = [
    { key: "digest", title: "Morning inbox digest", description: "A one-line summary of every unread email, every morning.", trigger: { type: "schedule", cron_expression: "0 8 * * *", timezone: TIMEZONE }, publish: true },
    { key: "standup", title: "Standup notes", description: "Turn yesterday's commits into standup notes.", trigger: { type: "manual" } },
    { key: "weekly", title: "Weekly review", description: "Every Friday, review the week's todos and plan the next.", trigger: { type: "schedule", cron_expression: "0 17 * * 5", timezone: TIMEZONE } },
  ];
  let useCaseSlug = null;
  for (const w of WORKFLOWS) {
    const created = await call("POST", "/workflows", {
      body: { title: w.title, description: w.description, prompt: `${w.description} Keep it short.`, trigger_config: w.trigger, steps: STEPS, notify_on_completion: true },
    });
    const workflow = created.workflow ?? created;
    workflows[w.key] = workflow.id;
    if (w.publish) useCaseSlug = (await call("POST", `/workflows/${workflow.id}/publish`)).slug;
  }
  if (!useCaseSlug) throw new Error("publishing the digest workflow returned no slug");

  return { userId: user.id, projects, todos, conversations, workflows, useCaseSlug };
}

async function seedOnboardingUser() {
  await resetUser(ONBOARDING_USER, { ownsWorkflows: false });
  const user = await dev("POST", "/users", { email: ONBOARDING_USER, name: "Sam Lee" });
  return { userId: user.id };
}

const review = await seedReviewUser();
const onboarding = await seedOnboardingUser();

execFileSync(
  "uv",
  ["run", "--group", "backend", "python", join(HERE, "seed_notifications.py"), review.userId, seededAt.toISOString()],
  { cwd: join(API_TREE, "apps/api"), stdio: "inherit", env: { ...process.env, LOG_LEVEL: "ERROR", PYTHONPATH: join(API_TREE, "apps/api") } },
);

const state = {
  seededAt: seededAt.toISOString(),
  api: API,
  users: { review: { email: REVIEW_USER, id: review.userId }, onboarding: { email: ONBOARDING_USER, id: onboarding.userId } },
  projects: review.projects,
  todos: review.todos,
  conversations: review.conversations,
  chatGroups: CHAT_GROUPS.map(({ key, title, tools }) => ({ key, title, tools })),
  workflows: review.workflows,
  useCaseSlug: review.useCaseSlug,
};
mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, "seed-state.json"), JSON.stringify(state, null, 2));
console.log(`seeded ${Object.keys(state.todos).length} todos, ${Object.keys(state.conversations).length} chats, ${Object.keys(state.workflows).length} workflows -> ${join(OUT, "seed-state.json")}`);
