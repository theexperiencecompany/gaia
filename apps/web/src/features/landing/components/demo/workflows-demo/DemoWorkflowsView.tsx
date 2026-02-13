"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  ArrowRight02Icon,
  PlayIcon,
  TimeScheduleIcon,
  UserGroupIcon,
  ZapIcon,
} from "@/icons";
import {
  DEMO_COMMUNITY_WORKFLOWS,
  DEMO_USER_WORKFLOWS,
} from "./workflowsDemoConstants";

function DemoWorkflowIcons({
  steps,
  iconSize = 25,
  maxIcons = 3,
}: {
  steps: Array<{ category: string }>;
  iconSize?: number;
  maxIcons?: number;
}) {
  const categories = [...new Set(steps.map((s) => s.category))];
  const displayIcons = categories.slice(0, maxIcons);

  return (
    <div className="flex min-h-8 items-center -space-x-1.5">
      {displayIcons.map((category, index) => (
        <div
          key={category}
          className="relative flex min-w-8 items-center justify-center"
          style={{
            rotate:
              displayIcons.length > 1
                ? index % 2 === 0
                  ? "8deg"
                  : "-8deg"
                : "0deg",
            zIndex: index,
          }}
        >
          {getToolCategoryIcon(category, {
            width: iconSize,
            height: iconSize,
          })}
        </div>
      ))}
      {categories.length > maxIcons && (
        <div
          className="z-0 flex items-center justify-center rounded-lg bg-zinc-700/60 text-zinc-400"
          style={{
            width: iconSize + 7,
            height: iconSize + 7,
            minWidth: iconSize + 7,
            fontSize: Math.max(10, iconSize * 0.5),
          }}
        >
          +{categories.length - maxIcons}
        </div>
      )}
    </div>
  );
}

function DemoWorkflowCard({
  title,
  description,
  steps,
  activated,
  totalExecutions,
  triggerLabel,
  variant = "user",
  creatorName,
}: {
  title: string;
  description: string;
  steps: Array<{ category: string; title?: string }>;
  activated?: boolean;
  totalExecutions?: number;
  triggerLabel?: string;
  variant?: "user" | "community";
  creatorName?: string;
}) {
  return (
    <div className="group relative z-1 flex h-full min-h-fit w-full flex-col gap-2 rounded-3xl outline-1 bg-zinc-800 outline-zinc-800/70 p-4 transition-all select-none cursor-pointer hover:bg-zinc-700/50">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <DemoWorkflowIcons steps={steps} iconSize={25} maxIcons={3} />
        </div>
        {variant === "user" && activated !== undefined && (
          <Chip
            color={activated ? "success" : "danger"}
            variant="flat"
            size="sm"
          >
            {activated ? "Activated" : "Deactivated"}
          </Chip>
        )}
      </div>

      <div>
        <h3 className="line-clamp-2 text-lg font-medium">{title}</h3>
        <div className="mt-1 line-clamp-2 min-h-8 flex-1 text-xs text-zinc-500">
          {description}
        </div>
      </div>

      <div className="mt-auto">
        <div className="mt-1 flex items-center justify-between gap-2">
          <div className="space-y-1">
            {variant === "user" && triggerLabel && (
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1 text-xs text-zinc-500">
                  <TimeScheduleIcon width={14} height={14} />
                  <span>{triggerLabel}</span>
                </div>
              </div>
            )}
            {totalExecutions !== undefined && totalExecutions > 0 && (
              <div className="flex items-center gap-1 text-xs text-zinc-500">
                <PlayIcon
                  width={15}
                  height={15}
                  className="w-4 text-zinc-500"
                />
                <span className="text-nowrap">
                  {totalExecutions >= 1000
                    ? `${(totalExecutions / 1000).toFixed(1)}k`
                    : totalExecutions}{" "}
                  runs
                </span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            {variant === "community" && creatorName && (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-700 text-xs font-medium text-zinc-300">
                {creatorName.charAt(0)}
              </div>
            )}
            <Button
              color="primary"
              size="sm"
              variant={variant === "user" ? "flat" : "solid"}
              className={`font-medium rounded-xl ${variant === "user" ? "text-primary" : ""}`}
              endContent={
                variant !== "user" ? (
                  <ZapIcon width={16} height={16} />
                ) : undefined
              }
            >
              {variant === "user" ? "Run" : "Create"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function DemoWorkflowsView() {
  return (
    <div className="space-y-8 overflow-y-auto p-4 sm:p-6 md:p-8">
      {/* Community Banner */}
      <div className="mb-6">
        <div className="relative flex items-center justify-between overflow-hidden rounded-3xl border border-zinc-800 bg-zinc-900/50 px-6 py-5">
          <div className="flex items-center gap-4">
            <UserGroupIcon className="h-6 w-6 text-primary" />
            <div>
              <h3 className="text-base font-semibold text-zinc-100">
                Explore the Community
              </h3>
              <p className="text-sm text-zinc-400">
                Discover community workflows or publish your own for others to
                use.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="flat"
              size="sm"
              endContent={<ArrowRight02Icon className="h-4 w-4" />}
            >
              Browse Use Cases
            </Button>
            <Button
              color="primary"
              size="sm"
              startContent={<ZapIcon className="h-4 w-4" />}
            >
              Create New Workflow
            </Button>
          </div>
        </div>
      </div>

      {/* User Workflows Grid */}
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {DEMO_USER_WORKFLOWS.map((wf) => (
            <DemoWorkflowCard
              key={wf.id}
              title={wf.title}
              description={wf.description}
              steps={wf.steps}
              activated={wf.activated}
              totalExecutions={wf.total_executions}
              triggerLabel={wf.trigger_label}
              variant="user"
            />
          ))}
        </div>
      </div>

      {/* Community Workflows Section */}
      <div className="mt-12 flex flex-col gap-3">
        <div className="flex flex-col space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-2xl font-medium text-zinc-100">
              Community Workflows
            </h2>
            <span className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-sm font-medium text-zinc-400">
              {DEMO_COMMUNITY_WORKFLOWS.length}
            </span>
          </div>
          <p className="font-light text-zinc-500">
            Check out what others have built and grab anything that looks
            useful!
          </p>
        </div>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {DEMO_COMMUNITY_WORKFLOWS.map((wf) => (
            <DemoWorkflowCard
              key={wf.id}
              title={wf.title}
              description={wf.description}
              steps={wf.steps}
              totalExecutions={wf.total_executions}
              variant="community"
              creatorName={wf.creator.name}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
