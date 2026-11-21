"use client";

import { InputGroup, TextArea } from "@heroui/react";
import { Search01Icon, Tick02Icon, ViewIcon, WebhookIcon } from "@icons";
import { type ReactNode, useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";
import { AppIcon } from "./AppIcon";
import { APP_NAMES, DEMO_TRIGGERS, defaultTriggerData } from "./demoTriggers";
import EventSettings from "./EventSettings";
import type { TaskWhen } from "./taskModel";
import WatchPane from "./WatchPane";
import WebhookSettings from "./WebhookSettings";
import { newWebhook, onEvent, WEBHOOK_TRIGGER } from "./whenModel";

type Change = (when: TaskWhen) => void;

/** What the pane shows: the list to choose from, or the one chosen. */
type Choice = "list" | "watch" | "event";

/** The two kinds that belong to no app, above the apps' own events. */
const ANYWHERE = [
  {
    key: "watch",
    name: "Something changes",
    hint: "a price, a reply",
    Icon: ViewIcon,
    words: "something changes watch price page site reply down",
  },
  {
    key: "webhook",
    name: "Webhook",
    hint: "from any app",
    Icon: WebhookIcon,
    words: "webhook url link stripe github",
  },
] as const;

function choiceOf(when: TaskWhen): Choice {
  if (when.kind === "watch") return "watch";
  if (when.kind === "event" && when.trigger) return "event";
  return "list";
}

/** The chosen kind as a 36px line that opens the list again. */
function Chosen({
  icon,
  name,
  onChange,
}: {
  icon: ReactNode;
  name: string;
  onChange: () => void;
}) {
  return (
    <GaiaButton
      size="sm"
      variant="sunken"
      shape="md"
      tone="strong"
      aria-label="Change what starts it"
      onPress={onChange}
      className="h-9 w-full justify-start gap-2 text-sm"
    >
      {icon}
      <span className="truncate">{name}</span>
      <span className="ml-auto text-[13px] text-zinc-500">Change</span>
    </GaiaButton>
  );
}

/** "Only when ...": the gate's condition, for an app event or a webhook. */
function OnlyWhen({ when, onChange }: { when: TaskWhen; onChange: Change }) {
  return (
    <div>
      <p className="px-1 pb-1.5 text-[13px] text-zinc-500">Only when</p>
      <TextArea
        aria-label="Only when"
        value={when.condition ?? ""}
        onChange={(event) =>
          onChange(
            onEvent(
              when.trigger ?? "",
              event.target.value,
              when.triggerData,
              when.webhook,
            ),
          )
        }
        placeholder={
          when.webhook ? "It's a new Pro plan" : "It has an invoice attached"
        }
        rows={2}
        className={inputVariants({
          variant: "sunken",
          placeholder: "subtle",
          className: toneVariants({
            tone: "white",
            className: "block w-full resize-none text-sm leading-5",
          }),
        })}
      />
      <p className="px-1 pt-1.5 text-xs text-zinc-500">
        Optional. GAIA skips everything else.
      </p>
    </div>
  );
}

/**
 * When something happens: an app's event, a webhook, or a change GAIA watches
 * for. Chosen from one list; the chosen one shows its settings in its place.
 */
export default function EventPane({
  when,
  onChange,
  limit,
}: {
  when: TaskWhen;
  onChange: Change;
  limit?: ReactNode;
}) {
  const [choice, setChoice] = useState<Choice>(() => choiceOf(when));
  const [query, setQuery] = useState("");
  const selected = DEMO_TRIGGERS.find((item) => item.slug === when.trigger);
  const relist = () => setChoice("list");

  if (choice === "watch") {
    return (
      <div className="space-y-3">
        <Chosen
          icon={<ViewIcon className="size-4 shrink-0 text-zinc-400" />}
          name="Something changes"
          onChange={relist}
        />
        <WatchPane when={when} onChange={onChange} />
      </div>
    );
  }

  if (choice === "event" && when.webhook) {
    return (
      <div className="space-y-3">
        <Chosen
          icon={<WebhookIcon className="size-4 shrink-0 text-zinc-400" />}
          name="Webhook"
          onChange={relist}
        />
        <WebhookSettings
          webhook={when.webhook}
          onChange={(webhook) =>
            onChange(
              onEvent(WEBHOOK_TRIGGER, when.condition, undefined, webhook),
            )
          }
        />
        <OnlyWhen when={when} onChange={onChange} />
        {limit}
      </div>
    );
  }

  if (choice === "event" && selected) {
    return (
      <div className="space-y-3">
        <Chosen
          icon={<AppIcon id={selected.app} size={16} />}
          name={selected.name}
          onChange={relist}
        />
        <EventSettings
          trigger={selected}
          data={when.triggerData ?? defaultTriggerData(selected)}
          onChange={(data) =>
            onChange(onEvent(selected.slug, when.condition, data))
          }
        />
        <OnlyWhen when={when} onChange={onChange} />
        {limit}
      </div>
    );
  }

  const needle = query.trim().toLowerCase();
  const anywhere = ANYWHERE.filter((item) => item.words.includes(needle));
  const matches = DEMO_TRIGGERS.filter((item) =>
    `${APP_NAMES[item.app]} ${item.name}`.toLowerCase().includes(needle),
  );
  const apps = [...new Set(matches.map((item) => item.app))];

  return (
    <div className="space-y-1">
      <InputGroup
        className={inputVariants({ variant: "sunken", className: "w-full" })}
      >
        <InputGroup.Prefix>
          <Search01Icon className="size-4 shrink-0 text-zinc-500" />
        </InputGroup.Prefix>
        <InputGroup.Input
          autoFocus
          aria-label="Search events"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search apps and events"
          className={toneVariants({ tone: "white", className: "text-sm" })}
        />
      </InputGroup>
      <div className="-mx-1 max-h-72 overflow-y-auto px-1">
        {anywhere.length > 0 && (
          <section className="pt-2">
            {anywhere.map((item) => {
              const isOn =
                item.key === "watch"
                  ? when.kind === "watch"
                  : when.trigger === WEBHOOK_TRIGGER;
              return (
                <GaiaButton
                  key={item.key}
                  size="sm"
                  variant="raised-ghost"
                  shape="md"
                  tone="bright"
                  onPress={() => {
                    setQuery("");
                    if (item.key === "watch") return setChoice("watch");
                    if (!isOn)
                      onChange(
                        onEvent(
                          WEBHOOK_TRIGGER,
                          undefined,
                          undefined,
                          newWebhook(),
                        ),
                      );
                    setChoice("event");
                  }}
                  className="h-9 w-full justify-start gap-2 text-sm"
                >
                  <item.Icon className="size-4 shrink-0 text-zinc-400" />
                  {item.name}
                  <span className="truncate text-[13px] text-zinc-500">
                    {item.hint}
                  </span>
                  {isOn && (
                    <Tick02Icon className="ml-auto size-4 shrink-0 text-zinc-400" />
                  )}
                </GaiaButton>
              );
            })}
          </section>
        )}
        {apps.map((app) => (
          <section key={app}>
            <h4 className="px-3 pt-3 pb-1 text-xs text-zinc-500">
              {APP_NAMES[app]}
            </h4>
            {matches
              .filter((item) => item.app === app)
              .map((item) => (
                <GaiaButton
                  key={item.slug}
                  size="sm"
                  variant="raised-ghost"
                  shape="md"
                  tone="bright"
                  onPress={() => {
                    if (item.slug !== when.trigger)
                      onChange(
                        onEvent(
                          item.slug,
                          when.condition,
                          defaultTriggerData(item),
                        ),
                      );
                    setQuery("");
                    setChoice("event");
                  }}
                  className="h-9 w-full justify-start gap-2 text-sm"
                >
                  <AppIcon id={item.app} size={15} />
                  {item.name}
                  {item.slug === when.trigger && (
                    <Tick02Icon className="ml-auto size-4 text-zinc-400" />
                  )}
                </GaiaButton>
              ))}
          </section>
        ))}
        {matches.length === 0 && anywhere.length === 0 && (
          <p className="px-2 py-6 text-center text-[13px] text-zinc-500">
            Nothing matches
          </p>
        )}
      </div>
    </div>
  );
}
