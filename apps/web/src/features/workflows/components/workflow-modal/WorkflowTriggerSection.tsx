import { Tabs } from "@heroui/react";
import { Clock01Icon, Cursor02Icon, FlashIcon } from "@icons";
import { getUserHomeTimezone } from "@/lib/timezone";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";
import { createDefaultTriggerConfig } from "../../triggers/registry";
import { ScheduleBuilder } from "../ScheduleBuilder";
import { TriggerConfigForm } from "../TriggerConfigForm";
import WorkflowSection from "./WorkflowSection";

interface WorkflowTriggerSectionProps {
  activeTab: WorkflowFormData["activeTab"];
  selectedTrigger: WorkflowFormData["selectedTrigger"];
  triggerConfig: WorkflowFormData["trigger_config"];
  onActiveTabChange: (tab: "manual" | "schedule" | "trigger") => void;
  onSelectedTriggerChange: (
    trigger: WorkflowFormData["selectedTrigger"],
  ) => void;
  onTriggerConfigChange: (config: WorkflowFormData["trigger_config"]) => void;
  isPreview?: boolean;
}

const TRIGGER_TABS = [
  { key: "manual", label: "Manual", icon: Cursor02Icon },
  { key: "schedule", label: "Schedule", icon: Clock01Icon },
  { key: "trigger", label: "Event", icon: FlashIcon },
] as const;

export default function WorkflowTriggerSection({
  activeTab,
  selectedTrigger,
  triggerConfig,
  onActiveTabChange,
  onSelectedTriggerChange,
  onTriggerConfigChange,
  isPreview = false,
}: WorkflowTriggerSectionProps) {
  const handleTabChange = (tabKey: "manual" | "schedule" | "trigger") => {
    onActiveTabChange(tabKey);

    // Set appropriate trigger config based on tab. Only change trigger_config
    // when the current config doesn't already match the selected tab.
    if (tabKey === "schedule") {
      if (triggerConfig.type !== "schedule") {
        onTriggerConfigChange({
          type: "schedule",
          enabled: true,
          cron_expression: "0 9 * * *",
          timezone: getUserHomeTimezone(),
        });
      }
    } else if (tabKey === "trigger") {
      const currentType = triggerConfig.type;
      const isTriggerType =
        currentType !== "schedule" && currentType !== "manual";

      // The config still belongs to another tab — reseed it from the previous
      // event selection so it always matches the Event tab being switched to.
      if (!isTriggerType) {
        const defaultConfig = selectedTrigger
          ? createDefaultTriggerConfig(selectedTrigger)
          : undefined;
        onTriggerConfigChange(
          defaultConfig ?? { type: "email", enabled: true },
        );
      }
    } else if (triggerConfig.type !== "manual") {
      onTriggerConfigChange({ type: "manual", enabled: true });
    }
  };

  const renderTabBody = (key: "manual" | "schedule" | "trigger") => {
    if (key === "manual") {
      return (
        <p className="text-sm text-zinc-400">
          This workflow runs only when you start it from here, the Workflows
          page, or chat.
        </p>
      );
    }

    if (key === "schedule") {
      return (
        <ScheduleBuilder
          value={
            triggerConfig.type === "schedule"
              ? (triggerConfig.cron_expression as string) || ""
              : ""
          }
          timezone={
            triggerConfig.type === "schedule"
              ? (triggerConfig.timezone as string) || getUserHomeTimezone()
              : getUserHomeTimezone()
          }
          onChange={(cronExpression) => {
            if (triggerConfig.type === "schedule") {
              onTriggerConfigChange({
                ...triggerConfig,
                cron_expression: cronExpression,
              });
            }
          }}
          onTimezoneChange={(tz) => {
            if (triggerConfig.type === "schedule") {
              onTriggerConfigChange({ ...triggerConfig, timezone: tz });
            }
          }}
        />
      );
    }

    return (
      <TriggerConfigForm
        selectedTrigger={selectedTrigger}
        triggerConfig={triggerConfig}
        onTriggerChange={onSelectedTriggerChange}
        onConfigChange={onTriggerConfigChange}
      />
    );
  };

  // In preview only the active mode is shown; otherwise all three are selectable.
  const visibleTabs = isPreview
    ? TRIGGER_TABS.filter((t) => t.key === activeTab)
    : TRIGGER_TABS;

  return (
    <WorkflowSection label="When should this run?">
      <Tabs
        selectedKey={activeTab}
        onSelectionChange={(key) =>
          handleTabChange(key as "manual" | "schedule" | "trigger")
        }
        className="w-full"
      >
        <Tabs.List
          aria-label="Trigger type"
          className="w-full rounded-xl bg-zinc-800/60 p-1"
        >
          {visibleTabs.map((tab) => (
            <Tabs.Tab
              key={tab.key}
              id={tab.key}
              className="h-9 font-medium text-zinc-400 data-[selected=true]:text-zinc-100"
            >
              <span className="flex items-center gap-1.5">
                <tab.icon className="h-4 w-4" />
                {tab.label}
              </span>
            </Tabs.Tab>
          ))}
        </Tabs.List>
        {visibleTabs.map((tab) => (
          <Tabs.Panel key={tab.key} id={tab.key}>
            <div className="pt-1.5">{renderTabBody(tab.key)}</div>
          </Tabs.Panel>
        ))}
      </Tabs>
    </WorkflowSection>
  );
}
