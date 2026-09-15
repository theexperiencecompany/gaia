"use client";

import { Button } from "@heroui/button";
import { Progress } from "@heroui/progress";
import { ArrowExpand01Icon, ArrowShrink02Icon } from "@icons";
import { AnimatePresence, useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import { FirstStepRow } from "@/features/first-steps/components/FirstStepRow";
import {
  FIRST_STEPS_ROW_STAGGER_SECONDS,
  FIRST_STEPS_TRANSITION,
  FIRST_STEPS_WIDGET_HIDDEN_PATHS,
} from "@/features/first-steps/constants";
import { useFirstStepAction } from "@/features/first-steps/hooks/useFirstStepAction";
import { useFirstSteps } from "@/features/first-steps/hooks/useFirstSteps";
import { usePathname } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

/**
 * Floating bottom-right version of the checklist, mounted once in the main
 * layout. It overlays the app, so unlike the dashboard card it carries a
 * collapse control — that is what the persisted `collapsed` flag is about.
 *
 * The progress bar belongs to the collapsed state only. Expanded, the rows are
 * the progress and a bar would just say the same thing twice; collapsed, it is
 * the only thing left saying how far along you are, so it rides in the header
 * beside the title.
 *
 * Desktop only. A floating corner panel needs a corner to float in: at phone
 * widths it spans the viewport and sits on top of the composer, so the first
 * thing the checklist asks you to do is the one thing it blocks. Phones get the
 * checklist as a card on the dashboard instead.
 */
export function FirstStepsWidget() {
  const pathname = usePathname();
  const {
    steps,
    doneCount,
    totalCount,
    isVisible,
    collapsed,
    toggleCollapsed,
  } = useFirstSteps();
  const runStep = useFirstStepAction("widget");
  const reduceMotion = useReducedMotion();

  if (FIRST_STEPS_WIDGET_HIDDEN_PATHS.includes(pathname) || !isVisible) {
    return null;
  }

  return (
    <aside
      aria-label="First steps"
      className={cn(
        "fixed right-4 bottom-4 z-40 hidden w-64 bg-zinc-800 shadow-lg sm:block",
        // Collapsed it is a single line of content, so it reads as a pill
        // rather than a panel with an empty body.
        collapsed ? "rounded-full px-4 py-2" : "rounded-3xl p-3",
      )}
    >
      <div className="flex items-center gap-3">
        <h3 className="shrink-0 text-sm font-medium text-zinc-300">
          First steps
        </h3>

        <AnimatePresence initial={false}>
          {collapsed && (
            <m.div
              key="progress"
              className="min-w-0 flex-1"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={FIRST_STEPS_TRANSITION}
            >
              <Progress
                aria-label={`${doneCount} of ${totalCount} first steps done`}
                value={doneCount}
                maxValue={totalCount}
                size="sm"
                classNames={{
                  track: "bg-zinc-700",
                  indicator: "bg-success transition-all duration-500 ease-out",
                }}
              />
            </m.div>
          )}
        </AnimatePresence>

        {collapsed ? (
          // Plain art while collapsed: the whole panel is the control (below),
          // and a button inside a button is not valid markup. It is sized to
          // the glyph, not to a button, so the pill can stay short.
          <span className="ml-auto grid size-5 shrink-0 place-items-center">
            <ArrowExpand01Icon className="size-4 text-zinc-400" />
          </span>
        ) : (
          <Button
            isIconOnly
            size="sm"
            variant="light"
            className="ml-auto cursor-pointer"
            aria-expanded
            aria-label="Collapse first steps"
            onPress={toggleCollapsed}
          >
            <ArrowShrink02Icon className="size-4 text-zinc-400" />
          </Button>
        )}
      </div>

      {/* The collapse rides on `grid-template-rows: 0fr -> 1fr`, not on height:
          animating height forces the browser to re-lay-out every frame, and
          `react-doctor/no-layout-property-animation` rejects it. The rows stay
          mounted and are made inert instead of unmounted, so the grid has a
          measured row to interpolate against. */}
      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none",
          collapsed ? "grid-rows-[0fr]" : "grid-rows-[1fr]",
        )}
      >
        {/* `inert` blocks focus and pointer, `aria-hidden` takes the rows out
            of the accessibility tree. Paired deliberately: alone, `aria-hidden`
            would leave focusable buttons announced as nothing, which is the
            ARIA violation it is usually blamed for. */}
        <div
          className="overflow-hidden"
          inert={collapsed || undefined}
          aria-hidden={collapsed || undefined}
        >
          <div className="flex flex-col pt-2">
            {steps.map((step, index) => (
              <m.div
                key={step.key}
                className="min-w-0"
                animate={{ opacity: collapsed ? 0 : 1 }}
                initial={false}
                transition={{
                  ...FIRST_STEPS_TRANSITION,
                  delay:
                    collapsed || reduceMotion
                      ? 0
                      : index * FIRST_STEPS_ROW_STAGGER_SECONDS,
                }}
              >
                <FirstStepRow step={step} onActivate={runStep} />
              </m.div>
            ))}
          </div>
        </div>
      </div>

      {/* Last child, so it paints over the panel and takes every click without
          any pointer-events juggling. Only mounted while collapsed, where
          nothing underneath it is interactive. */}
      {collapsed && (
        <button
          type="button"
          aria-label="Expand first steps"
          aria-expanded={false}
          onClick={toggleCollapsed}
          className="absolute inset-0 cursor-pointer rounded-full transition-colors duration-200 hover:bg-white/5 focus-visible:bg-white/5 focus-visible:outline-none"
        />
      )}
    </aside>
  );
}
