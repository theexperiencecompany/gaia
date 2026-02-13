import { Tab, Tabs } from "@heroui/tabs";
import { Tooltip } from "@heroui/tooltip";
import { InformationCircleIcon } from "@icons";
import {
  getBrowserTimezone,
  type WorkflowFormData,
} from "../../schemas/workflowFormSchema";
import { ScheduleBuilder } from "../ScheduleBuilder";
import { TriggerConfigForm } from "../TriggerConfigForm";

interface WorkflowTriggerSectionProps {
  activeTab: WorkflowFormData["activeTab"];
  selectedTrigger: WorkflowFormData["selectedTrigger"];
  triggerConfig: WorkflowFormData["trigger_config"];
  onActiveTabChange: (tab: "manual" | "schedule" | "trigger") => void;
  onSelectedTriggerChange: (
    trigger: WorkflowFormData["selectedTrigger"],
  ) => void;
  onTriggerConfigChange: (config: WorkflowFormData["trigger_config"]) => void;
}

export default function WorkflowTriggerSection({
  activeTab,
  selectedTrigger,
  triggerConfig,
  onActiveTabChange,
  onSelectedTriggerChange,
  onTriggerConfigChange,
}: WorkflowTriggerSectionProps) {
  const handleTabChange = (tabKey: "manual" | "schedule" | "trigger") => {
    onActiveTabChange(tabKey);

    // Set appropriate trigger config based on tab
    // Only change trigger_config if the current config doesn't match the tab
    if (tabKey === "schedule") {
      // Only reset if not already a schedule type
      if (triggerConfig.type !== "schedule") {
        onTriggerConfigChange({
          type: "schedule",
          enabled: true,
          cron_expression: "0 9 * * *",
          timezone: getBrowserTimezone(),
        });
      }
    } else if (tabKey === "trigger") {
      // Preserve existing trigger selection if it's a trigger type
      // Only reset if current type is schedule or manual
      const currentType = triggerConfig.type;
      const isTriggerType =
        currentType !== "schedule" && currentType !== "manual";

      if (!isTriggerType) {
        // Check if we have a previously selected trigger
        if (selectedTrigger) {
          // Don't change config - let TriggerConfigForm handle it
          // The selectedTrigger is preserved in form state
        } else {
          // No previous selection, set to email as default
          onTriggerConfigChange({
            type: "email",
            enabled: true,
          });
        }
      }
      // If already a trigger type, keep current config
    } else {
      // Manual tab - only reset if not already manual
      if (triggerConfig.type !== "manual") {
        onTriggerConfigChange({
          type: "manual",
          enabled: true,
        });
      }
    }
  };

  const renderTriggerTab = () => (
    <TriggerConfigForm
      selectedTrigger={selectedTrigger}
      triggerConfig={triggerConfig}
      onTriggerChange={onSelectedTriggerChange}
      onConfigChange={onTriggerConfigChange}
    />
  );

  const renderManualTab = () => (
    <div className="w-full">
      <p className="text-sm text-zinc-500">
        This workflow will be triggered manually when you run it.
      </p>
    </div>
  );

  const renderScheduleTab = () => (
    <div className="w-full">
      <ScheduleBuilder
        value={
          triggerConfig.type === "schedule"
            ? (triggerConfig.cron_expression as string) || ""
            : ""
        }
        onChange={(cronExpression) => {
          if (triggerConfig.type === "schedule") {
            onTriggerConfigChange({
              ...triggerConfig,
              cron_expression: cronExpression,
            });
          }
        }}
      />
    </div>
  );

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3">
        <div className="mt-2.5 flex min-w-26 items-center justify-between gap-1.5 text-sm font-medium text-zinc-400">
          <span className="text-nowrap">When to Run</span>
          <Tooltip
            content={
              <div className="px-1 py-2">
                <p className="text-sm font-medium">When to Run</p>
                <p className="mt-1 text-xs text-zinc-400">
                  Choose how your workflow will be activated:
                </p>
                <ul className="mt-2 space-y-1 text-xs text-zinc-400">
                  <li>
                    • <span className="font-medium">Manual:</span> Run the
                    workflow manually when you need it
                  </li>
                  <li>
                    • <span className="font-medium">Schedule:</span> Run at
                    specific times or intervals
                  </li>
                  <li>
                    • <span className="font-medium">Trigger:</span> Run when
                    external events occur (coming soon)
                  </li>
                </ul>
              </div>
            }
            placement="top"
            delay={500}
          >
            <InformationCircleIcon className="h-3.5 w-3.5 cursor-help text-zinc-500 hover:text-zinc-300" />
          </Tooltip>
        </div>
        <div className="w-full">
          <Tabs
            color="primary"
            classNames={{
              tabList: "flex flex-row",
              base: "flex items-start",
              tabWrapper: "w-full",
              panel: "min-w-full",
            }}
            className="w-full"
            selectedKey={activeTab}
            onSelectionChange={(key) => {
              handleTabChange(key as "manual" | "schedule" | "trigger");
            }}
          >
            <Tab key="schedule" title="Schedule">
              {renderScheduleTab()}
            </Tab>
            <Tab key="trigger" title="Trigger">
              {renderTriggerTab()}
            </Tab>
            <Tab key="manual" title="Manual">
              {renderManualTab()}
            </Tab>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
