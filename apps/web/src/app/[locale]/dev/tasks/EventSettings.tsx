"use client";

import { Switch } from "@heroui/react";

import { switchVariants } from "@/components/shared/controlVariants";
import type { DemoTrigger, TriggerSetting } from "./demoTriggers";
import PickMenu from "./PickMenu";
import type { TriggerData } from "./taskModel";
import { Field } from "./WhenParts";

const settingSwitch = switchVariants();

type PickSetting = Extract<TriggerSetting, { kind: "pick" }>;

/** "Personal", "Personal, Work", "3 calendars"; an empty choice reads as all, or asks for one. */
function pickSummary(setting: PickSetting, ids: string[]): string {
  if (ids.length === 0) return setting.allLabel ?? "Choose";
  const names = ids.map(
    (id) => setting.options.find((option) => option.id === id)?.label ?? id,
  );
  return names.length <= 2
    ? names.join(", ")
    : `${names.length} ${setting.label.toLowerCase()}`;
}

const minutesLabel = (minutes: number) =>
  minutes % 60 === 0
    ? `${minutes / 60} hour${minutes === 60 ? "" : "s"} before`
    : `${minutes} min before`;

/**
 * The chosen event's own settings, one 36px line each, in the order its trigger
 * schema lists them. An event whose schema takes none shows nothing.
 */
export default function EventSettings({
  trigger,
  data,
  onChange,
}: {
  trigger: DemoTrigger;
  data: TriggerData;
  onChange: (data: TriggerData) => void;
}) {
  if (!trigger.settings?.length) return null;
  const set = (key: string, value: TriggerData[string]) =>
    onChange({ ...data, [key]: value });

  return (
    <div className="space-y-2">
      {trigger.settings.map((setting) => {
        if (setting.kind === "toggle") {
          return (
            <Field key={setting.key} label={setting.label}>
              <Switch
                aria-label={setting.label}
                isSelected={data[setting.key] === true}
                onChange={(on) => set(setting.key, on)}
              >
                <Switch.Control className={settingSwitch.control()}>
                  <Switch.Thumb className={settingSwitch.thumb()} />
                </Switch.Control>
              </Switch>
            </Field>
          );
        }
        if (setting.kind === "minutes") {
          const minutes = Number(data[setting.key] ?? setting.initial);
          return (
            <Field key={setting.key} label={setting.label}>
              <PickMenu
                label={setting.label}
                summary={minutesLabel(minutes)}
                options={setting.choices.map((choice) => ({
                  id: String(choice),
                  label: minutesLabel(choice),
                }))}
                selected={[String(minutes)]}
                isMultiple={false}
                onPick={(id) => set(setting.key, Number(id))}
              />
            </Field>
          );
        }
        const raw = data[setting.key];
        // Several ids are a list (repos, calendar_ids); one is a plain id (Linear's team_id).
        const ids = Array.isArray(raw) ? raw : raw ? [String(raw)] : [];
        return (
          <Field key={setting.key} label={setting.label}>
            <PickMenu
              label={setting.label}
              summary={pickSummary(setting, ids)}
              isPlaceholder={ids.length === 0 && !setting.allLabel}
              options={setting.options}
              selected={ids}
              isMultiple={setting.isMultiple}
              onPick={(id) => {
                const isOn = ids.includes(id);
                if (!setting.isMultiple) set(setting.key, isOn ? "" : id);
                else
                  set(
                    setting.key,
                    isOn ? ids.filter((other) => other !== id) : [...ids, id],
                  );
              }}
            />
          </Field>
        );
      })}
    </div>
  );
}
