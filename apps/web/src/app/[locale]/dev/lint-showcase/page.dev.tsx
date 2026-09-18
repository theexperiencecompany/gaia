"use client";

import type { JSX, ReactNode } from "react";
import CalendarEventSection from "@/features/chat/components/bubbles/bot/CalendarEventSection";
import RateLimitCard from "@/features/chat/components/bubbles/bot/RateLimitCard";
import TwitterSearchSection from "@/features/chat/components/bubbles/bot/TwitterSearchSection";
import CalendarEventSectionBefore from "./before/CalendarEventSectionBefore";
import RateLimitCardBefore from "./before/RateLimitCardBefore";
import TwitterSearchSectionBefore from "./before/TwitterSearchSectionBefore";
import { MOCK_CALENDAR_OPTIONS, MOCK_RATE_LIMIT } from "./mocks";
import {
  FULL_CARD_EXAMPLES,
  formatShowcaseBadge,
  getPairCount,
  getRuleStatus,
  MOCK_TWEETS,
  RULE_GUIDE,
  type RuleGuide,
  SHOWCASE_EXEMPTIONS,
  SHOWCASE_SECTIONS,
} from "./showcase-data";

interface ShowcasePairProps {
  rule: string;
  title: string;
  change: string;
  badge: string;
  before: ReactNode;
  beforeCaption: string;
  afterCaption: string;
  children: ReactNode;
}

function DiffCaption({
  text,
  other,
}: {
  text: string;
  other: string;
}): JSX.Element {
  const shared = new Set(other.split(/\s+/));
  // Static caption string: keys combine token + occurrence count so repeats
  // stay unique without the array index (noArrayIndexKey).
  const seen = new Map<string, number>();
  const keyFor = (token: string): string => {
    const count = (seen.get(token) ?? 0) + 1;
    seen.set(token, count);
    return `${token}@${count}`;
  };
  return (
    <p className="mt-1 break-words font-mono text-xs">
      {text.split(/(\s+)/).map((token) =>
        /^\s+$/.test(token) ? (
          <span key={keyFor("ws")}>{token}</span>
        ) : (
          <span
            key={keyFor(token)}
            className={shared.has(token) ? "text-zinc-400" : "text-red-400"}
          >
            {token}
          </span>
        ),
      )}
    </p>
  );
}

export function ShowcasePair({
  rule,
  title,
  change,
  badge,
  before,
  beforeCaption,
  afterCaption,
  children,
}: ShowcasePairProps): JSX.Element {
  return (
    <section className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-1 flex items-center gap-2">
        <span className="rounded-xl bg-zinc-700 px-2 py-0.5 font-mono text-xs font-medium text-zinc-200 tabular-nums">
          {badge}
        </span>
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-100">
          {title}
        </p>
        <span className="shrink-0 rounded-full bg-zinc-700/50 px-2 py-0.5 font-mono text-xs text-zinc-400">
          {rule}
        </span>
      </div>
      <p className="mb-3 text-xs text-zinc-500">{change}</p>
      <div className="flex flex-col gap-2">
        <div className="flex-1">
          <p className="mb-1 text-xs font-medium text-red-400">Before</p>
          <div className="rounded-2xl bg-zinc-950 p-3">{before}</div>
          <DiffCaption text={beforeCaption} other={afterCaption} />
        </div>
        <div className="flex-1">
          <p className="mb-1 text-xs font-medium text-emerald-400">After</p>
          <div className="rounded-2xl bg-zinc-950 p-3">{children}</div>
          <DiffCaption text={afterCaption} other={beforeCaption} />
        </div>
      </div>
    </section>
  );
}

interface FullCardPairProps {
  title: string;
  change: string;
  badge: string;
  before: ReactNode;
  beforeCaption: string;
  afterCaption: string;
  children: ReactNode;
}

function FullCardPair({
  title,
  change,
  badge,
  before,
  beforeCaption,
  afterCaption,
  children,
}: FullCardPairProps): JSX.Element {
  return (
    <section className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-1 flex items-center gap-2">
        <span className="rounded-xl bg-zinc-700 px-2 py-0.5 font-mono text-xs font-medium text-zinc-200 tabular-nums">
          {badge}
        </span>
        <p className="text-sm font-semibold text-zinc-100">{title}</p>
      </div>
      <p className="mt-0.5 text-xs text-zinc-500">{change}</p>
      <div className="mt-3 flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-medium text-red-400">Before</p>
          <div className="rounded-2xl bg-zinc-950 p-3">{before}</div>
          <DiffCaption text={beforeCaption} other={afterCaption} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-medium text-emerald-400">After</p>
          <div className="rounded-2xl bg-zinc-950 p-3">{children}</div>
          <DiffCaption text={afterCaption} other={beforeCaption} />
        </div>
      </div>
    </section>
  );
}

function RuleSummaryTable(): JSX.Element {
  return (
    <section className="rounded-2xl bg-zinc-800 p-4">
      <h2 className="text-sm font-semibold text-zinc-100">Rules at a glance</h2>
      <p className="mt-1 text-xs text-zinc-500">
        Six rules. Select a rule to jump to its examples.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-zinc-500">
              <th className="pb-2 pr-4 font-medium" scope="col">
                Rule
              </th>
              <th className="pb-2 pr-4 font-medium" scope="col">
                What it catches
              </th>
              <th className="pb-2 pr-4 font-medium" scope="col">
                Pairs
              </th>
              <th className="pb-2 font-medium" scope="col">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {RULE_GUIDE.map((guide) => (
              <tr className="border-t border-zinc-700/50" key={guide.rule}>
                <td className="py-2 pr-4">
                  <a
                    className="font-mono text-zinc-100 underline decoration-zinc-600 underline-offset-2"
                    href={`#${guide.rule}`}
                  >
                    {guide.rule}
                  </a>
                </td>
                <td className="py-2 pr-4 text-zinc-400">{guide.what}</td>
                <td className="py-2 pr-4 text-zinc-400">
                  {getPairCount(guide.rule)}
                </td>
                <td className="py-2 text-zinc-400">
                  {getRuleStatus(guide.params)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RuleSection({ guide }: { guide: RuleGuide }): JSX.Element {
  const fullCards = FULL_CARD_EXAMPLES.filter(
    (example) => example.rule === guide.rule,
  );
  const snippets = SHOWCASE_SECTIONS.filter(
    (section) => section.rule === guide.rule,
  );
  const pairCount = fullCards.length + snippets.length;
  return (
    <details className="flex scroll-mt-8 flex-col gap-4" id={guide.rule}>
      <summary className="cursor-pointer rounded-2xl bg-zinc-800 p-4">
        <span className="font-mono text-sm font-semibold text-zinc-100">
          {guide.rule}
        </span>
        <span className="ml-2 text-xs text-zinc-500">({pairCount} pairs)</span>
      </summary>
      <div className="rounded-2xl bg-zinc-800 p-4">
        <p className="text-xs leading-relaxed text-zinc-400">
          <span className="font-semibold text-zinc-200">What it catches: </span>
          {guide.what}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-zinc-400">
          <span className="font-semibold text-zinc-200">
            Why it exists in GAIA:{" "}
          </span>
          {guide.why}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-zinc-400">
          <span className="font-semibold text-zinc-200">Our settings: </span>
          {guide.params}
        </p>
      </div>
      {fullCards.length > 0 ? (
        <div className="flex flex-col gap-3 rounded-2xl border border-zinc-700/50 p-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              <h3 className="text-sm font-semibold text-zinc-100">
                Full tool cards
              </h3>
              <span className="rounded-xl bg-zinc-700 px-2 py-0.5 font-mono text-xs text-zinc-400">
                {fullCards.length} pairs
              </span>
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              Full-component renders. Before and After stay side by side.
            </p>
          </div>
          <div className="flex flex-col gap-4">
            {fullCards.map((example, index) => (
              <FullCardPair
                afterCaption={example.afterCaption}
                badge={formatShowcaseBadge(index + 1)}
                before={example.before}
                beforeCaption={example.beforeCaption}
                change={example.change}
                key={example.title}
                title={example.title}
              >
                {example.after}
              </FullCardPair>
            ))}
          </div>
        </div>
      ) : null}
      {snippets.length > 0 ? (
        <div className="flex flex-col gap-3 rounded-2xl border border-zinc-700/50 p-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-blue-400" />
              <h3 className="text-sm font-semibold text-zinc-100">
                Token-level fixes
              </h3>
              <span className="rounded-xl bg-zinc-700 px-2 py-0.5 font-mono text-xs text-zinc-400">
                {snippets.length} pairs
              </span>
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              Small token fixes. Two-up grid on desktop.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {snippets.map((section, index) => (
              <ShowcasePair
                afterCaption={section.afterCaption}
                badge={formatShowcaseBadge(fullCards.length + index + 1)}
                before={section.before}
                beforeCaption={section.beforeCaption}
                change={section.change}
                key={section.title}
                rule={section.rule}
                title={section.title}
              >
                {section.after}
              </ShowcasePair>
            ))}
          </div>
        </div>
      ) : null}
    </details>
  );
}

interface RadiusShowdownPairProps {
  title: string;
  before: ReactNode;
  children: ReactNode;
}

function RadiusShowdownPair({
  title,
  before,
  children,
}: RadiusShowdownPairProps): JSX.Element {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm font-semibold text-zinc-100">{title}</p>
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-medium text-red-400">
            Before (old code)
          </p>
          <div className="rounded-2xl bg-zinc-950 p-3">{before}</div>
        </div>
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-medium text-emerald-400">
            After (current)
          </p>
          <div className="rounded-2xl bg-zinc-950 p-3">{children}</div>
        </div>
      </div>
    </div>
  );
}

function RadiusShowdownSection(): JSX.Element {
  return (
    <section className="rounded-2xl bg-zinc-800 p-4">
      <h2 className="text-sm font-semibold text-zinc-100">
        Rounded 2xl vs 3xl
      </h2>
      <p className="mt-1 text-xs text-zinc-500">
        Rule flipped: chat outers are now 3xl. Real old components left, new
        live components right.
      </p>
      <div className="mt-3 flex flex-col gap-4">
        <RadiusShowdownPair
          before={
            <CalendarEventSectionBefore
              calendar_options={MOCK_CALENDAR_OPTIONS}
            />
          }
          title="CalendarEventSection"
        >
          <CalendarEventSection calendar_options={MOCK_CALENDAR_OPTIONS} />
        </RadiusShowdownPair>
        <RadiusShowdownPair
          before={<RateLimitCardBefore data={MOCK_RATE_LIMIT} />}
          title="RateLimitCard"
        >
          <RateLimitCard data={MOCK_RATE_LIMIT} />
        </RadiusShowdownPair>
        <RadiusShowdownPair
          before={
            <TwitterSearchSectionBefore twitter_search_data={MOCK_TWEETS} />
          }
          title="TwitterSearchSection"
        >
          <TwitterSearchSection twitter_search_data={MOCK_TWEETS} />
        </RadiusShowdownPair>
      </div>
    </section>
  );
}

export default function LintShowcasePage(): JSX.Element {
  return (
    <div className="flex-1 overflow-y-auto px-8 py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-100">Lint Showcase</h1>
        <p className="mt-1 text-xs text-zinc-500">
          The six active design-system rules from apps/web/.oxlintrc.json, each
          with its reason, our settings, and live before-versus-after renders.
          Sections are collapsed by default; expand one to see its pairs.
        </p>
      </div>
      <div className="flex w-full max-w-5xl flex-col gap-8">
        <RadiusShowdownSection />
        <RuleSummaryTable />
        {RULE_GUIDE.map((guide) => (
          <RuleSection guide={guide} key={guide.rule} />
        ))}
        <details className="rounded-2xl bg-zinc-800 p-4">
          <summary className="cursor-pointer text-sm">
            <span className="font-semibold text-zinc-100">
              Deliberate exemptions
            </span>
            <span className="ml-2 text-xs text-zinc-500">
              ({SHOWCASE_EXEMPTIONS.length} items)
            </span>
          </summary>
          <p className="mt-3 text-xs text-zinc-500">
            Carve-outs in .oxlintrc.json allow-lists and overrides, each kept
            for one reason.
          </p>
          <ul className="mt-3 flex flex-col gap-1.5">
            {SHOWCASE_EXEMPTIONS.map((exemption) => (
              <li
                className="flex items-baseline gap-2 text-xs"
                key={exemption.label}
              >
                <span className="shrink-0 font-medium text-zinc-200">
                  {exemption.label}
                </span>
                <span className="text-zinc-500">{exemption.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  );
}
