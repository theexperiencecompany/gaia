"use client";

import { Autocomplete, AutocompleteItem } from "@heroui/autocomplete";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Skeleton } from "@heroui/skeleton";
import { PlusSignIcon, Search01Icon } from "@icons";
import * as m from "motion/react-m";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";

/** Rows of pills shown before any "Show more", and revealed per click. */
const INITIAL_ROWS = 3;
const ROWS_PER_CLICK = 3;
/** Rough chip height + row gap; only seeds the first paint before measurement. */
const ESTIMATED_ROW_PX = 44;

const SKELETON_COUNT = 12;
const SKELETON_KEYS = Array.from(
  { length: SKELETON_COUNT },
  (_, i) => `pill-skeleton-${i}`,
);

// Fallback ordering when the caller doesn't pass `priorityNames`. Matched
// case-insensitively by name; anything not listed keeps the catalog order.
const DEFAULT_PRIORITY_NAMES = [
  "gmail",
  "google calendar",
  "google docs",
  "google sheets",
  "slack",
  "notion",
  "github",
];

interface IntegrationChipsSelectorProps {
  readonly selectedSlugs: string[];
  readonly onChange: (slugs: string[]) => void;
  /**
   * "connected" (default) — only show integrations the user has connected.
   * "catalog" — show the full integration catalog (used during onboarding).
   */
  readonly source?: "connected" | "catalog";
  /**
   * Presentation. "autocomplete" (default) — compact dropdown used in the
   * workflow modal. "pills" — clickable pill-cloud picker used during onboarding.
   */
  readonly variant?: "autocomplete" | "pills";
  /**
   * Integration display names (matched case-insensitively) surfaced first in
   * the "pills" picker, in order. Falls back to a general popular set.
   */
  readonly priorityNames?: string[];
  /**
   * Extra classes for the "pills" search + cloud wrapper (e.g. a left inset to
   * align with surrounding chat messages). The "Show more" button stays
   * centered on the full width regardless.
   */
  readonly pillContentClassName?: string;
  /** Override the Autocomplete input width class (default: "max-w-sm"). */
  readonly autocompleteClassName?: string;
}

function IntegrationIcon({
  integration,
  size = 14,
}: {
  integration: Integration;
  size?: number;
}) {
  return getToolCategoryIcon(
    integration.id,
    { size, width: size, height: size, showBackground: false },
    integration.iconUrl,
  );
}

function IntegrationChipsSelector({
  selectedSlugs,
  onChange,
  source = "connected",
  variant = "autocomplete",
  priorityNames,
  pillContentClassName,
  autocompleteClassName = "max-w-sm",
}: IntegrationChipsSelectorProps) {
  const { integrations, isLoading } = useIntegrations();

  const sourceIntegrations = useMemo(
    () =>
      source === "catalog"
        ? integrations
        : integrations.filter(
            (i) => i.status === "connected" || i.status === "created",
          ),
    [integrations, source],
  );

  const selectedSlugSet = useMemo(
    () => new Set(selectedSlugs),
    [selectedSlugs],
  );

  const addIntegration = useCallback(
    (slug: string) => {
      if (!selectedSlugSet.has(slug)) onChange([...selectedSlugs, slug]);
    },
    [onChange, selectedSlugs, selectedSlugSet],
  );

  const removeIntegration = useCallback(
    (slug: string) => {
      onChange(selectedSlugs.filter((s) => s !== slug));
    },
    [onChange, selectedSlugs],
  );

  const toggleIntegration = useCallback(
    (slug: string) => {
      if (selectedSlugSet.has(slug)) removeIntegration(slug);
      else addIntegration(slug);
    },
    [selectedSlugSet, addIntegration, removeIntegration],
  );

  // Hide only when not loading, no source integrations, and no selected slugs.
  // If selected slugs exist for now-disconnected integrations, keep rendering so
  // users can see and remove them.
  if (
    !isLoading &&
    sourceIntegrations.length === 0 &&
    selectedSlugs.length === 0
  )
    return null;

  if (variant === "pills") {
    return (
      <IntegrationPillCloud
        integrations={sourceIntegrations}
        isLoading={isLoading}
        selectedSlugSet={selectedSlugSet}
        onToggle={toggleIntegration}
        priorityNames={priorityNames ?? DEFAULT_PRIORITY_NAMES}
        contentClassName={pillContentClassName}
      />
    );
  }

  return (
    <IntegrationAutocomplete
      integrations={integrations}
      sourceIntegrations={sourceIntegrations}
      selectedSlugs={selectedSlugs}
      selectedSlugSet={selectedSlugSet}
      isLoading={isLoading}
      onAdd={addIntegration}
      onRemove={removeIntegration}
      autocompleteClassName={autocompleteClassName}
    />
  );
}

interface IntegrationAutocompleteProps {
  readonly integrations: Integration[];
  readonly sourceIntegrations: Integration[];
  readonly selectedSlugs: string[];
  readonly selectedSlugSet: Set<string>;
  readonly isLoading: boolean;
  readonly onAdd: (slug: string) => void;
  readonly onRemove: (slug: string) => void;
  readonly autocompleteClassName: string;
}

function IntegrationAutocomplete({
  integrations,
  sourceIntegrations,
  selectedSlugs,
  selectedSlugSet,
  isLoading,
  onAdd,
  onRemove,
  autocompleteClassName,
}: IntegrationAutocompleteProps) {
  const [inputValue, setInputValue] = useState("");

  const allIntegrationsBySlug = useMemo(
    () => new Map(integrations.map((i) => [i.slug, i])),
    [integrations],
  );

  const availableIntegrations = useMemo(() => {
    const query = inputValue.trim().toLowerCase();
    return sourceIntegrations.filter(
      (i) =>
        !selectedSlugSet.has(i.slug) &&
        (query === "" || i.name.toLowerCase().includes(query)),
    );
  }, [sourceIntegrations, selectedSlugSet, inputValue]);

  const handleSelectionChange = useCallback(
    (key: React.Key | null) => {
      if (key == null) return;
      onAdd(String(key));
      setInputValue("");
    },
    [onAdd],
  );

  return (
    <div className="flex flex-col gap-2">
      {sourceIntegrations.length > 0 && (
        <Autocomplete
          aria-label="Add integration to this workflow"
          placeholder={
            selectedSlugs.length === 0
              ? "Select integrations"
              : "Add integration"
          }
          description="Suggest Apps GAIA should use in this workflow"
          size="sm"
          variant="flat"
          isLoading={isLoading}
          items={availableIntegrations}
          selectedKey={null}
          inputValue={inputValue}
          onInputChange={setInputValue}
          onSelectionChange={handleSelectionChange}
          menuTrigger="focus"
          className={autocompleteClassName}
        >
          {(integration) => (
            <AutocompleteItem
              key={integration.slug}
              textValue={integration.name}
              startContent={<IntegrationIcon integration={integration} />}
            >
              {integration.name}
            </AutocompleteItem>
          )}
        </Autocomplete>
      )}

      {selectedSlugs.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {selectedSlugs.map((slug) => {
            const integration = allIntegrationsBySlug.get(slug);
            return (
              <Chip
                key={slug}
                size="sm"
                variant="flat"
                color="primary"
                as="button"
                type="button"
                onClick={() => onRemove(slug)}
                onClose={() => onRemove(slug)}
                aria-label={`Remove ${integration?.name ?? slug}`}
                startContent={
                  integration ? (
                    <span className="ml-1 flex items-center">
                      <IntegrationIcon integration={integration} />
                    </span>
                  ) : undefined
                }
                className="cursor-pointer transition-colors hover:bg-primary/30"
              >
                {integration?.name ?? slug}
              </Chip>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface IntegrationPillCloudProps {
  readonly integrations: Integration[];
  readonly isLoading: boolean;
  readonly selectedSlugSet: Set<string>;
  readonly onToggle: (slug: string) => void;
  readonly priorityNames: string[];
  readonly contentClassName?: string;
}

/** Scroll the nearest scrollable ancestor to the bottom (to reveal new rows). */
function scrollAncestorToBottom(node: HTMLElement | null): void {
  let el = node?.parentElement ?? null;
  while (el) {
    const overflowY = getComputedStyle(el).overflowY;
    if (
      (overflowY === "auto" || overflowY === "scroll") &&
      el.scrollHeight > el.clientHeight
    ) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      return;
    }
    el = el.parentElement;
  }
}

interface PillRowMeasurement {
  rowByPosition: number[];
  clampHeight: number | null;
  hasMore: boolean;
}

/** Group the wrap's children into rows (by distinct offsetTop) and compute the
 *  max-height that clips the cloud to `visibleRows` whole rows. */
function measurePillRows(
  el: HTMLDivElement,
  visibleRows: number,
): PillRowMeasurement {
  const children = Array.from(el.children) as HTMLElement[];
  if (children.length === 0) {
    return { rowByPosition: [], clampHeight: null, hasMore: false };
  }
  const baseTop = children[0].offsetTop;
  const rowTops: number[] = [];
  for (const child of children) {
    if (!rowTops.includes(child.offsetTop)) rowTops.push(child.offsetTop);
  }
  rowTops.sort((a, b) => a - b);
  const rowByPosition = children.map((c) => rowTops.indexOf(c.offsetTop));

  if (visibleRows >= rowTops.length) {
    return { rowByPosition, clampHeight: null, hasMore: false };
  }
  const lastVisibleTop = rowTops[visibleRows - 1];
  const rowChild =
    children.find((c) => c.offsetTop === lastVisibleTop) ?? children[0];
  return {
    rowByPosition,
    clampHeight: lastVisibleTop - baseTop + rowChild.offsetHeight,
    hasMore: true,
  };
}

interface PillChipProps {
  readonly integration: Integration;
  readonly isSelected: boolean;
  /** Within the current clamp (visible) vs clipped below it. */
  readonly shown: boolean;
  readonly delay: number;
  readonly onToggle: (slug: string) => void;
}

function PillChip({
  integration,
  isSelected,
  shown,
  delay,
  onToggle,
}: PillChipProps) {
  return (
    <m.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: shown ? 1 : 0, scale: shown ? 1 : 0.96 }}
      // Transforms/opacity don't affect layout, so row measurement stays valid.
      transition={{ duration: 0.22, delay, ease: "easeOut" }}
    >
      <Chip
        as="button"
        type="button"
        onClick={() => onToggle(integration.slug)}
        aria-pressed={isSelected}
        // Pills clipped below the clamp stay mounted; keep them out of tab order
        // + a11y tree until "Show more" reveals them.
        tabIndex={shown ? undefined : -1}
        aria-hidden={shown ? undefined : true}
        size="lg"
        variant="flat"
        color={isSelected ? "success" : "default"}
        startContent={
          <span className="ml-1 flex items-center">
            <IntegrationIcon integration={integration} size={16} />
          </span>
        }
        className="cursor-pointer"
      >
        {integration.name}
      </Chip>
    </m.div>
  );
}

function IntegrationPillCloud({
  integrations,
  isLoading,
  selectedSlugSet,
  onToggle,
  priorityNames,
  contentClassName,
}: IntegrationPillCloudProps) {
  const [query, setQuery] = useState("");
  const [visibleRows, setVisibleRows] = useState(INITIAL_ROWS);
  // Seed with an estimate so the first paint is already roughly clamped;
  // the measure effect refines it to an exact row boundary.
  const [clampHeight, setClampHeight] = useState<number | null>(
    INITIAL_ROWS * ESTIMATED_ROW_PX,
  );
  const [hasMore, setHasMore] = useState(false);
  // Row each pill landed on, by position in `filtered` (measured from the DOM).
  const [rowByPosition, setRowByPosition] = useState<number[]>([]);
  const wrapRef = useRef<HTMLDivElement>(null);
  // Rows already shown before the latest "Show more"; stagger the new batch
  // relative to this so each reveal cascades from its first new pill.
  const revealedFromRowRef = useRef(0);
  // Skip the scroll-into-view on first mount; only run it after a reveal.
  const revealPendingRef = useRef(false);

  const isSearching = query.trim().length > 0;

  const priorityRank = useMemo(
    () =>
      new Map(priorityNames.map((name, index) => [name.toLowerCase(), index])),
    [priorityNames],
  );

  // Priority-first; everything else keeps catalog order (Array.sort is stable).
  // All matches render; the cloud is clipped to whole rows via maxHeight, so
  // toggling a pill never reorders or reflows the layout.
  const ordered = useMemo(() => {
    const rank = (i: Integration) =>
      priorityRank.get(i.name.trim().toLowerCase()) ?? Number.POSITIVE_INFINITY;
    return [...integrations].sort((a, b) => rank(a) - rank(b));
  }, [integrations, priorityRank]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ordered;
    return ordered.filter((i) => i.name.toLowerCase().includes(q));
  }, [ordered, query]);

  // Measure pill rows (by distinct offsetTop): record each pill's row, and
  // clamp the cloud to `visibleRows` whole rows. Re-runs on resize and whenever
  // the rendered set changes. While searching everything shows (no clamp).
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;

    const measure = () => {
      const next = isSearching
        ? { rowByPosition: [], clampHeight: null, hasMore: false }
        : measurePillRows(el, visibleRows);
      setRowByPosition(next.rowByPosition);
      setClampHeight(next.clampHeight);
      setHasMore(next.hasMore);
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [isSearching, visibleRows, filtered]);

  // After a "Show more" reveal, wait for the clamp transition then scroll the
  // freshly revealed rows into view once.
  useEffect(() => {
    if (!revealPendingRef.current) return;
    revealPendingRef.current = false;
    const id = setTimeout(() => scrollAncestorToBottom(wrapRef.current), 260);
    return () => clearTimeout(id);
  }, [visibleRows]);

  const handleShowMore = () => {
    revealedFromRowRef.current = visibleRows;
    revealPendingRef.current = true;
    setVisibleRows((rows) => rows + ROWS_PER_CLICK);
  };

  const batchStart = revealedFromRowRef.current;
  const batchStartIndex = Math.max(
    0,
    rowByPosition.findIndex((row) => row >= batchStart),
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Search + pills are inset (via contentClassName) to align with the
          surrounding chat messages; "Show more" below stays centered. */}
      <div className={`flex flex-col gap-3 ${contentClassName ?? ""}`}>
        <Input
          aria-label="Search apps"
          placeholder="Search apps…"
          size="md"
          variant="flat"
          value={query}
          onValueChange={setQuery}
          isClearable
          onClear={() => setQuery("")}
          startContent={
            <Search01Icon width={16} height={16} className="text-zinc-500" />
          }
          classNames={{ base: "max-w-xs" }}
        />

        {/* Fixed min-height so filtering swaps pills in place without resizing
            the page (which would shift scroll position). */}
        <div className="min-h-[7.5rem]">
          {isLoading ? (
            <div className="flex flex-wrap gap-2">
              {SKELETON_KEYS.map((key) => (
                <Skeleton key={key} className="h-9 w-28 rounded-full" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <p className="py-6 text-center text-xs text-zinc-500">
              No apps match “{query}”.
            </p>
          ) : (
            <div
              ref={wrapRef}
              className="flex flex-wrap gap-2 overflow-hidden transition-[max-height] duration-200"
              style={
                clampHeight != null ? { maxHeight: clampHeight } : undefined
              }
            >
              {filtered.map((integration, index) => {
                const row = rowByPosition[index] ?? 0;
                const shown = isSearching || row < visibleRows;
                // Stagger relative to the first pill of the current reveal batch,
                // so each "Show more" cascades from its start (not the list start).
                const order = Math.max(0, index - batchStartIndex);
                return (
                  <PillChip
                    key={integration.slug}
                    integration={integration}
                    isSelected={selectedSlugSet.has(integration.slug)}
                    shown={shown}
                    delay={shown ? Math.min(order, 18) * 0.025 : 0}
                    onToggle={onToggle}
                  />
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Fixed-height slot so the cloud doesn't shrink (shifting layout) when
          the button disappears on the last page. */}
      <div className="flex h-10 items-center justify-center">
        {hasMore && (
          <Button
            size="sm"
            variant="flat"
            radius="full"
            onPress={handleShowMore}
            startContent={
              <span className="flex items-center">
                <PlusSignIcon width={14} height={14} />
              </span>
            }
            className="text-zinc-300"
          >
            Show more
          </Button>
        )}
      </div>
    </div>
  );
}

export default memo(IntegrationChipsSelector);
