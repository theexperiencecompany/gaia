"use client";

import { Button, Chip, Slider, Switch, Textarea } from "@heroui/react";
import { OPENUI_SAMPLES } from "@shared/utils";
import { useCallback, useEffect, useState } from "react";

import { BASE_MESSAGE_SCHEMA } from "@/config/registries/baseMessageRegistry";

import TextBubble from "@/features/chat/components/bubbles/bot/TextBubble";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { SimpleChatBubbleBot } from "@/features/landing/components/demo/SimpleChatBubbles";

// streamdown animation config baked into MarkdownRenderer (shown read-only here).
const ANIMATION_CONFIG: [string, string][] = [
  ["Effect", "Blur in"],
  ["Duration", "250ms"],
  ["Easing", "ease-out"],
  ["Split by", "Word"],
  ["Stagger", "80ms"],
];

// Required-but-unused TextBubble callbacks in this preview-only context.
const noop = () => undefined;

const openuiFence = (name: string): string => {
  const code = OPENUI_SAMPLES.find((s) => s.name === name)?.code ?? "";
  return `:::openui\n${code}\n:::`;
};

const SAMPLE_USER = `Hey, can you show me **everything** the renderer supports? I want to see a proper table, a fenced code block, a task list, a blockquote, and some inline math like $E = mc^2$ rendered nicely. Basically throw the whole kitchen sink at it so I can check that nothing looks off while it streams in word by word. Don't hold back 🙂`;

// Comprehensive tour of every markdown feature the GAIA renderer supports.
const SAMPLE_BOT = [
  "# Streamdown in GAIA",
  "",
  'A tour of every markdown feature, animated word-by-word with a **blur-in** effect. Smart quotes turn "straight" into "curly", plus super^2^ / sub~2~ scripts, ~~strikethrough~~, and `inline code`.',
  "",
  "## Lists",
  "",
  "- Unordered item",
  "  - Nested, with a [link](https://gaia.computer)",
  "- Another item",
  "",
  "1. First",
  "2. Second",
  "",
  "- [x] Migrate to streamdown",
  "- [ ] Ship the demo",
  "",
  "## Quote & rule",
  "",
  "> Proactive, not reactive — that's the whole idea.",
  "",
  "---",
  "",
  "## Table",
  "",
  "| Feature | Before | After |",
  "| --- | --- | --- |",
  "| Renderer | react-markdown | streamdown |",
  "| Animation | none | blur-in |",
  "| Math | KaTeX | KaTeX (plugin) |",
  "",
  "## Code",
  "",
  "```python",
  "def greet(name: str) -> str:",
  '    return f"Hello, {name}!"',
  "```",
  "",
  "## Math",
  "",
  "Inline: $a^2 + b^2 = c^2$. Display:",
  "",
  "$$\\int_0^\\infty e^{-x}\\,dx = 1$$",
  "",
  "## OpenUI",
  "",
  "Rendered outside the bubble via the real OpenUI pipeline:",
  "",
  openuiFence("Timeline"),
  "",
  openuiFence("Steps"),
].join("\n");

/**
 * Tokenize for the reveal: word-by-word, but keep each `:::openui … :::` fence
 * whole. The OpenUI renderer parses incrementally and chokes on a half-streamed
 * fence (unclosed strings), so — like a backend that buffers a tool block — we
 * reveal each fence atomically and only ever hand it complete code.
 */
function tokenizeForReveal(full: string): string[] {
  const fence = /:::openui[\s\S]*?\n:::/g;
  // One token per word with its surrounding whitespace attached — preserves
  // indentation and blank lines while keeping the reveal at one word per tick.
  const words = (s: string): string[] => s.match(/\s*\S+\s*/g) ?? [];
  const tokens: string[] = [];
  let last = 0;
  let match: RegExpExecArray | null = fence.exec(full);
  while (match !== null) {
    tokens.push(...words(full.slice(last, match.index)));
    tokens.push(match[0]);
    last = match.index + match[0].length;
    match = fence.exec(full);
  }
  tokens.push(...words(full.slice(last)));
  return tokens;
}

/**
 * Reveal `full` while streaming, `burstSize` tokens per tick — burstSize=1 is
 * smooth token streaming; a larger value simulates a fast model dumping a whole
 * chunk per commit, which is what the MarkdownRenderer smoothing buffer absorbs.
 */
function useStreamedText(
  full: string,
  streaming: boolean,
  speedMs: number,
  runId: number,
  burstSize: number,
): string {
  const [shown, setShown] = useState(full);
  useEffect(() => {
    if (!streaming) {
      setShown(full);
      return;
    }
    const tokens = tokenizeForReveal(full);
    let i = 0;
    setShown("");
    const id = setInterval(() => {
      i += burstSize;
      setShown(tokens.slice(0, i).join(""));
      if (i >= tokens.length) clearInterval(id);
    }, speedMs);
    return () => clearInterval(id);
  }, [full, streaming, speedMs, runId, burstSize]);
  return shown;
}

/**
 * The streaming previews live in their own component so the per-token reveal
 * state stays here — re-rendering only the bubbles, not the controls/textareas.
 * (The HeroUI Textareas auto-measure their height on every render via
 * react-textarea-autosize; re-rendering them per token forced a layout reflow.)
 */
function Previews({
  userText,
  botText,
  streaming,
  speedMs,
  runId,
  burstSize,
}: {
  userText: string;
  botText: string;
  streaming: boolean;
  speedMs: number;
  runId: number;
  burstSize: number;
}) {
  const userShown = useStreamedText(
    userText,
    streaming,
    speedMs,
    runId,
    burstSize,
  );
  const botShown = useStreamedText(
    botText,
    streaming,
    speedMs,
    runId,
    burstSize,
  );
  const botLoading = streaming && botShown !== botText;
  const userLoading = streaming && userShown !== userText;

  return (
    <>
      {/* Real chat bubbles (TextBubble + ChatBubbleUser) */}
      <div className="flex flex-col gap-2 rounded-2xl bg-zinc-950 p-6">
        <span className="mb-2 text-xs font-medium tracking-wide text-zinc-500">
          REAL BUBBLES
        </span>
        <div className="flex flex-col items-start">
          <TextBubble
            {...BASE_MESSAGE_SCHEMA}
            text={botShown}
            loading={botLoading}
            message_id="demo-bot"
            tool_data={[]}
            setOpenImage={noop}
            setImageData={noop}
          />
        </div>
        <ChatBubbleUser
          {...BASE_MESSAGE_SCHEMA}
          text={userShown}
          loading={userLoading}
          message_id="demo-user"
          disableActions
        />
      </div>

      {/* Shared landing-demo simple bubbles wrapping the bare MarkdownRenderer */}
      <div className="flex flex-col gap-4 rounded-2xl bg-zinc-950 p-6">
        <span className="text-xs font-medium tracking-wide text-zinc-500">
          SIMPLE BUBBLES
        </span>
        <SimpleChatBubbleBot>
          <MarkdownRenderer content={botShown} isStreaming={botLoading} />
        </SimpleChatBubbleBot>
        <div className="flex w-full justify-end">
          <div className="imessage-bubble imessage-from-me">
            <MarkdownRenderer
              content={userShown}
              isStreaming={userLoading}
              lightBackground
            />
          </div>
        </div>
      </div>
    </>
  );
}

export default function DemoBody() {
  const [streaming, setStreaming] = useState(true);
  const [speedMs, setSpeedMs] = useState(55);
  const [burstSize, setBurstSize] = useState(1);
  const [userText, setUserText] = useState(SAMPLE_USER);
  const [botText, setBotText] = useState(SAMPLE_BOT);
  const [runId, setRunId] = useState(0);

  const replay = useCallback(() => setRunId((n) => n + 1), []);
  // Restart the reveal when the streaming knobs change (not on every keystroke).
  useEffect(() => {
    replay();
  }, [streaming, speedMs, burstSize, replay]);

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-5xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-xl font-medium text-white">
          Streamdown markdown + animation
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          The real bot bubble (TextBubble) and user bubble (ChatBubbleUser)
          rendering through the migrated MarkdownRenderer. Adjust Stream speed
          and Burst (words per commit) to see how streamdown animates smooth vs
          chunky token arrivals.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {ANIMATION_CONFIG.map(([label, value]) => (
            <Chip key={label} size="sm" variant="flat">
              <span className="text-zinc-500">{label}:</span>{" "}
              <span className="text-zinc-200">{value}</span>
            </Chip>
          ))}
        </div>
      </div>

      {/* Controls */}
      <div className="grid grid-cols-1 gap-4 rounded-2xl bg-zinc-900 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Slider
          label="Stream speed (ms/tick)"
          minValue={10}
          maxValue={300}
          step={5}
          value={speedMs}
          onChange={(v) => setSpeedMs(Array.isArray(v) ? v[0] : v)}
          getValue={(v) => `${v}ms`}
          isDisabled={!streaming}
        />
        <Slider
          label="Burst (words/tick)"
          minValue={1}
          maxValue={40}
          step={1}
          value={burstSize}
          onChange={(v) => setBurstSize(Array.isArray(v) ? v[0] : v)}
          getValue={(v) => `${v}`}
          isDisabled={!streaming}
        />
        <div className="flex items-center">
          <Switch isSelected={streaming} onValueChange={setStreaming}>
            Stream
          </Switch>
        </div>
        <div className="flex items-center justify-end">
          <Button color="primary" onPress={replay}>
            Replay
          </Button>
        </div>
      </div>

      {/* Editable content */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Textarea
          label="User message (markdown)"
          value={userText}
          onValueChange={setUserText}
          minRows={2}
          maxRows={6}
        />
        <Textarea
          label="Bot message (markdown)"
          value={botText}
          onValueChange={setBotText}
          minRows={2}
          maxRows={6}
        />
      </div>

      <Previews
        userText={userText}
        botText={botText}
        streaming={streaming}
        speedMs={speedMs}
        runId={runId}
        burstSize={burstSize}
      />
    </div>
  );
}
