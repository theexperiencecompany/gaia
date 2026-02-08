import { Tab, Tabs } from "@heroui/tabs";
import { Tooltip } from "@heroui/tooltip";
import { InformationCircleIcon } from "@/icons";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";
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
              onActiveTabChange(key as "manual" | "schedule" | "trigger");
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
