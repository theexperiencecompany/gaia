"use client";

import { Select, SelectItem } from "@heroui/select";
import { notFound } from "next/navigation";
import { useMemo, useState } from "react";
import { FIXTURES } from "./fixtures";
import {
  VariantGrouped,
  VariantManageMode,
  VariantSearchBulk,
} from "./variants";

const VARIANTS = [
  {
    key: "manage",
    title: "A — Manage mode",
    blurb:
      "Plain tool list; switches only appear behind an explicit Manage approvals button.",
    Component: VariantManageMode,
  },
  {
    key: "grouped",
    title: "B — Grouped",
    blurb:
      "Asks-first expanded, runs-automatically collapsed. Two numbers instead of N rows.",
    Component: VariantGrouped,
  },
  {
    key: "search",
    title: "C — Search + bulk",
    blurb:
      "Search box and ask-all/allow-all bulk actions, built for 100+ tool integrations.",
    Component: VariantSearchBulk,
  },
] as const;

export default function ToolApprovalsPrototypePage() {
  if (process.env.NODE_ENV === "production") notFound();

  const [fixtureId, setFixtureId] = useState(FIXTURES[1].id);
  const fixture = useMemo(
    () => FIXTURES.find((f) => f.id === fixtureId) ?? FIXTURES[0],
    [fixtureId],
  );
  // One shared local approval set per fixture — switching variants keeps state
  // so the comparison is about layout, not data. Never touches real HIL prefs.
  const [gatedByFixture, setGatedByFixture] = useState<
    Record<string, Set<string>>
  >({});
  const gated = useMemo(
    () =>
      gatedByFixture[fixture.id] ??
      new Set(fixture.tools.filter((t) => t.destructive).map((t) => t.name)),
    [gatedByFixture, fixture],
  );
  const onToggle = (name: string, next: boolean) => {
    setGatedByFixture((prev) => {
      const current = new Set(
        prev[fixture.id] ??
          fixture.tools.filter((t) => t.destructive).map((t) => t.name),
      );
      if (next) {
        current.add(name);
      } else {
        current.delete(name);
      }
      return { ...prev, [fixture.id]: current };
    });
  };

  return (
    <div className="h-screen overflow-y-auto p-8">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100">
            Tool approvals — UX prototypes
          </h1>
          <p className="text-sm text-zinc-500">
            Dev-only. Local state, real sidebar width (320px), no writes to HIL
            preferences.
          </p>
        </div>
        <Select
          label="Fixture"
          size="sm"
          className="w-64"
          selectedKeys={[fixtureId]}
          onSelectionChange={(keys) => {
            const key = [...keys][0];
            if (typeof key === "string") setFixtureId(key);
          }}
        >
          {FIXTURES.map((f) => (
            <SelectItem key={f.id}>{f.name}</SelectItem>
          ))}
        </Select>
      </div>

      <div className="flex flex-wrap gap-6">
        {VARIANTS.map(({ key, title, blurb, Component }) => (
          <div key={key} className="w-80 shrink-0">
            <h2 className="text-sm font-medium text-zinc-200">{title}</h2>
            <p className="mb-3 min-h-8 text-xs text-zinc-500">{blurb}</p>
            <div className="rounded-2xl bg-zinc-900 p-4">
              <Component
                tools={fixture.tools}
                gated={gated}
                onToggle={onToggle}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
