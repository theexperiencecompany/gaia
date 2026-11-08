/**
 * bot-handles — every WhatsApp, Telegram and Discord link in the repo points at
 * the handles the apps import. The README, docs and the API's discovery prompt
 * repeat them as plain text no import can reach, so this scan is what keeps
 * those copies from drifting.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const BOT_HANDLES_SOURCE = "libs/shared/bot-identity.json";

// Fixtures mint links from stand-in handles on purpose: the API suite and this
// gate's own tests write links that must not be held to the real handles.
const EXCLUDED_PATHS = [
  ":(exclude)apps/api/tests/**",
  ":(exclude)scripts/ci/tests/**",
  ":(exclude,glob)**/__tests__/**",
];

// Docs legitimately send people to Telegram's BotFather, which is not GAIA's.
const ALLOWED_HANDLES = { Telegram: new Set(["botfather"]) };

const GREP_PATTERN =
  "wa\\.me/[0-9]+|t\\.me/[[:alnum:]_]+|discord\\.gg/[[:alnum:]-]+|discord(app)?\\.com/invite/[[:alnum:]-]+|discord\\.heygaia\\.io";

const LINK_PATTERNS = [
  { kind: "WhatsApp", pattern: /wa\.me\/(\d+)/g, key: "whatsappNumber" },
  {
    kind: "Telegram",
    pattern: /t\.me\/([A-Za-z0-9_]+)/g,
    key: "telegramUsername",
  },
  { kind: "Discord", pattern: /discord\.gg\/([A-Za-z0-9-]+)/g, key: "discordCode" },
  {
    kind: "Discord",
    pattern: /discord\.heygaia\.io/g,
    key: "discordCommunity",
    host: true,
  },
  {
    kind: "Discord",
    pattern: /discord(?:app)?\.com\/invite\/([A-Za-z0-9-]+)/g,
    key: "discordCode",
  },
];

function readHandles() {
  let source = "{}";
  try {
    source = readFileSync(BOT_HANDLES_SOURCE, "utf8");
  } catch {
    // Missing file is the same failure as a missing handle: the gate has no
    // canonical value to compare against, so it must fail, not pass silently.
  }
  const identity = JSON.parse(source);
  const handles = {
    whatsappNumber: identity.whatsappNumber,
    telegramUsername: identity.telegramUsername,
    discordCode: identity.discordInviteCode,
    discordCommunity: identity.discordCommunityUrl,
  };
  const missing = [];
  for (const [name, value] of Object.entries(handles)) {
    if (!value) missing.push(name);
  }
  if (missing.length > 0) {
    console.error(
      `❌ bot-handles gate FAILED — ${BOT_HANDLES_SOURCE} no longer exports: ${missing.join(", ")}.`,
    );
    console.error(
      "The gate reads the canonical handles from those constants; restore them or update this check.",
    );
    process.exit(1);
  }
  return handles;
}

function linkMatches() {
  try {
    return execFileSync(
      "git",
      ["grep", "-nI", "-E", GREP_PATTERN, "--", ...EXCLUDED_PATHS],
      { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
    );
  } catch (error) {
    if (error.status === 1) return "";
    throw error;
  }
}

/** Compares the identifier a link names, not the URL shape that carries it. */
function disagrees(kind, found, handles, host) {
  if (kind === "Discord" && host) {
    return found !== new URL(handles.discordCommunity).host;
  }
  if (ALLOWED_HANDLES[kind]?.has(found.toLowerCase())) return false;
  if (kind === "WhatsApp") return found !== handles.whatsappNumber;
  if (kind === "Telegram") {
    return found.toLowerCase() !== handles.telegramUsername.toLowerCase();
  }
  return found !== handles.discordCode;
}

/** Fails when a link names a handle other than the canonical constants. */
export function runBotHandles() {
  const handles = readHandles();
  const offenders = [];
  const checked = { WhatsApp: 0, Telegram: 0, Discord: 0 };

  for (const raw of linkMatches().split("\n")) {
    if (!raw) continue;
    const parsed = raw.match(/^(.*?):(\d+):(.*)$/);
    if (!parsed) continue;
    const [, file, line, text] = parsed;
    for (const { kind, pattern, key, host } of LINK_PATTERNS) {
      pattern.lastIndex = 0;
      for (const match of text.matchAll(pattern)) {
        const found = host ? match[0] : match[1];
        checked[kind] += 1;
        if (disagrees(kind, found, handles, host)) {
          const expected = host ? new URL(handles[key]).host : handles[key];
          offenders.push({ file, line, kind, found, expected });
        }
      }
    }
  }

  if (offenders.length > 0) {
    console.error(
      `\n❌ bot-handles gate FAILED — ${offenders.length} bot link(s) disagree with ${BOT_HANDLES_SOURCE}.\n`,
    );
    console.error(
      `Expected: WhatsApp ${handles.whatsappNumber} · Telegram @${handles.telegramUsername} · Discord ${handles.discordCode}\n`,
    );
    for (const offender of offenders) {
      console.error(
        `  ${offender.file}:${offender.line}  ${offender.kind} ${offender.found}  → expected ${offender.expected}`,
      );
    }
    console.error(
      "\nFix: point each link at the handle in that constant. The README, docs and" +
        " API prompt carry the handles as text, so changing one is a hand edit in" +
        " each of them and this gate catches the copy that was missed.",
    );
    process.exit(1);
  }

  console.log(
    `✅ Every bot link matches (WhatsApp ${checked.WhatsApp}, Telegram ${checked.Telegram}, Discord ${checked.Discord}).`,
  );
}
