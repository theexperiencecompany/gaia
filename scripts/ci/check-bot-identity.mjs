#!/usr/bin/env node
/**
 * check-bot-identity.mjs — the handles we publish versus the systems that answer.
 * Other gates prove our copies agree; this proves the handles still exist and
 * still say GAIA. A channel that resolves to a different bot answers 200, so the
 * checks compare page titles, not status codes.
 *
 * Env: KAPSO_API_KEY, TELEGRAM_BOT_TOKEN (both required).
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const SOURCE = "libs/shared/bot-identity.json";

const identity = JSON.parse(readFileSync(SOURCE, "utf8"));
const failures = [];

const pass = (label, detail) => console.log(`✅ ${label} — ${detail}`);
const fail = (label, detail) => {
  failures.push({ label, detail });
  console.log(`❌ ${label} — ${detail}`);
};

/** curl, not fetch: t.me resets Node's TLS handshake often enough to red the job. */
function curl(args) {
  return execFileSync(
    "curl",
    [
      "-sS",
      "--max-time",
      "20",
      // t.me resets connections from CI networks often enough that a single
      // attempt would page someone for the network, not for a broken handle.
      "--retry",
      "4",
      "--retry-delay",
      "1",
      "--retry-all-errors",
      ...args,
    ],
    {
    encoding: "utf8",
    timeout: 60_000,
  });
}

/** The display name a messenger's link preview shows for the handle. */
function previewTitle(url) {
  const html = curl(["-L", url]);
  const meta = html.match(/<meta[^>]+property="og:title"[^>]+content="([^"]*)"/i);
  return (meta?.[1] ?? "").trim();
}

async function checkWhatsapp() {
  const title = await previewTitle(`https://wa.me/${identity.whatsappNumber}`);
  if (!title) {
    fail("WhatsApp", "the wa.me page has no title; the link may be dead");
  } else if (/share on whatsapp/i.test(title)) {
    fail("WhatsApp", `+${identity.whatsappNumber} has no WhatsApp account`);
  } else if (title.toLowerCase() !== identity.displayName.toLowerCase()) {
    fail("WhatsApp", `+${identity.whatsappNumber} answers as "${title}", not "${identity.displayName}"`);
  } else {
    pass("WhatsApp", `+${identity.whatsappNumber} answers as ${title}`);
  }
}

async function checkTelegram() {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    fail(
      "Telegram",
      "TELEGRAM_BOT_TOKEN is not set; add it as a repository secret so the bot's own account is asked, not a scraped page",
    );
    return;
  }
  // getMe answers for the token's bot, so a handle edited to anything else fails.
  // fetch, not curl: the token must never appear in an argv an error would echo.
  const response = await fetch(`https://api.telegram.org/bot${token}/getMe`, {
    signal: AbortSignal.timeout(15_000),
  });
  const body = await response.json();
  if (!body.ok) {
    fail("Telegram", `getMe was refused: ${body.description ?? response.status}`);
    return;
  }
  const { username, first_name: firstName } = body.result;
  if (username.toLowerCase() !== identity.telegramUsername.toLowerCase()) {
    fail(
      "Telegram",
      `the bot token belongs to @${username}, the file says @${identity.telegramUsername}`,
    );
  } else {
    pass("Telegram", `@${username} (${firstName})`);
  }
}

async function checkDiscord() {
  const location = curl(["-o", "/dev/null", "-w", "%{redirect_url}", identity.discordCommunityUrl]).trim();
  if (!location.includes(identity.discordInviteCode)) {
    fail(
      "Discord",
      `${identity.discordCommunityUrl} redirects to ${location || "nothing"}, not invite ${identity.discordInviteCode}`,
    );
  } else {
    pass("Discord", `${identity.discordCommunityUrl} redirects to invite ${identity.discordInviteCode}`);
  }
}

function checkKapso() {
  const apiKey = process.env.KAPSO_API_KEY;
  if (!apiKey) {
    fail(
      "Kapso",
      "KAPSO_API_KEY is not set; add it as a repository secret so the live number is checked, not just the copy",
    );
    return;
  }
  // The key travels in the env the CLI already reads, never in argv.
  const output = execFileSync(
    "npx",
    ["-y", "@kapso/cli", "whatsapp", "numbers", "list", "--output", "json"],
    { encoding: "utf8", maxBuffer: 32 * 1024 * 1024, timeout: 120_000 },
  );
  const numbers = JSON.parse(output).data ?? [];
  const production = numbers.find((number) => number.kind === "production");
  if (!production) {
    fail("Kapso", "the project has no production WhatsApp number");
    return;
  }
  const live = production.display_phone_number_normalized ?? "";
  if (live !== identity.whatsappNumber) {
    fail(
      "Kapso",
      `production answers on ${production.display_phone_number}, the file says +${identity.whatsappNumber}`,
    );
  } else if (production.status !== "CONNECTED") {
    fail("Kapso", `${production.display_phone_number} is ${production.status}, not CONNECTED`);
  } else {
    pass("Kapso", `${production.display_phone_number} ${production.status}`);
  }
}

async function main() {
  const checks = [
    ["WhatsApp", checkWhatsapp],
    ["Telegram", checkTelegram],
    ["Discord", checkDiscord],
    ["Kapso", async () => checkKapso()],
  ];
  for (const [label, check] of checks) {
    try {
      await check();
    } catch (error) {
      fail(label, `${error.name}: ${error.message}`);
    }
  }

  if (failures.length > 0) {
    for (const { label, detail } of failures) console.log(`::error::${label}: ${detail}`);
    console.log(
      `\n${failures.length} bot identity check(s) failed. The website and the bots ship from ${SOURCE}; fix the handle or the system it points at.`,
    );
    process.exit(1);
  }
  console.log("\nEvery published handle answers as GAIA.");
}

await main();
