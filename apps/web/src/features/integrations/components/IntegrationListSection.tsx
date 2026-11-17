import {
  Accordion,
  AccordionItem,
  Chip,
  type Key,
  Link,
  ScrollShadow,
  Tooltip,
} from "@heroui/react";
import { ArrowRight02Icon, ConnectIcon, InformationCircleIcon } from "@icons";
import { type ReactNode, useState } from "react";
import { accordionVariants } from "@/components/shared/accordionVariants";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { toneVariants } from "@/components/shared/tone";
import {
  IntegrationRow,
  SuggestedIntegrationRow,
} from "@/features/integrations/components/IntegrationListRows";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { SuggestedIntegration } from "@/features/integrations/types";

const accordionStyles = accordionVariants({ density: "compact" });

type SectionKey = "connected" | "suggested" | "available";

const byName = (a: { name: string }, b: { name: string }) =>
  a.name.localeCompare(b.name);

interface ListSectionProps {
  id: SectionKey;
  title: string;
  count: number;
  tooltip: string;
  children: ReactNode;
}

/** One collapsible group of the list: its title, item count and what the group holds. */
function ListSection({
  id,
  title,
  count,
  tooltip,
  children,
}: ListSectionProps) {
  return (
    <AccordionItem id={id}>
      <Accordion.Heading>
        <Accordion.Trigger
          className={`cursor-pointer text-xs font-semibold ${toneVariants({ tone: "muted" })} ${accordionStyles.trigger()}`}
        >
          <div className="flex items-center gap-2">
            <span>{title}</span>
            <Chip
              size="sm"
              variant="soft"
              className={toneVariants({
                tone: "muted",
                className:
                  "text-xs aspect-square flex items-center justify-center",
              })}
            >
              {count}
            </Chip>
            <Tooltip>
              <Tooltip.Trigger className="ml-auto">
                <InformationCircleIcon
                  width={18}
                  height={18}
                  className="text-zinc-500 cursor-help"
                >
                  <title>Information</title>
                </InformationCircleIcon>
              </Tooltip.Trigger>
              <Tooltip.Content placement="top">{tooltip}</Tooltip.Content>
            </Tooltip>
          </div>
          <Accordion.Indicator className={accordionStyles.indicator()} />
        </Accordion.Trigger>
      </Accordion.Heading>
      <Accordion.Panel>
        <div className="pb-4">{children}</div>
      </Accordion.Panel>
    </AccordionItem>
  );
}

/** Expanded sections: each opens once, the first render it has items (data can land after mount); the user's toggles stand after that. */
function useAutoExpandedSections(populated: readonly SectionKey[]) {
  const [expandedKeys, setExpandedKeys] = useState<Set<Key>>(new Set());
  const [autoOpened, setAutoOpened] = useState<ReadonlySet<SectionKey>>(
    new Set(),
  );
  const newlyPopulated = populated.filter((key) => !autoOpened.has(key));
  if (newlyPopulated.length > 0) {
    setAutoOpened(new Set([...autoOpened, ...newlyPopulated]));
    setExpandedKeys(new Set([...expandedKeys, ...newlyPopulated]));
  }
  return { expandedKeys, setExpandedKeys };
}

interface IntegrationListSectionProps {
  suggestedIntegrations?: SuggestedIntegration[];
}

function IntegrationListSection({
  suggestedIntegrations = [],
}: IntegrationListSectionProps) {
  const { integrations, connectIntegration, refetch } = useIntegrations();

  const connected = integrations
    .filter((i) => i.status === "connected")
    .toSorted(byName);
  const notConnected = integrations
    .filter((i) => i.status !== "connected")
    .toSorted(byName);

  const populated: SectionKey[] = [];
  if (connected.length > 0) populated.push("connected");
  if (suggestedIntegrations.length > 0) populated.push("suggested");
  if (notConnected.length > 0) populated.push("available");
  const { expandedKeys, setExpandedKeys } = useAutoExpandedSections(populated);

  return (
    <CollapsibleListWrapper
      icon={<ConnectIcon size={20} />}
      count={integrations.length}
      label="Integrations"
      isCollapsible={true}
    >
      <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-4 text-white">
        <Accordion
          allowsMultipleExpanded
          expandedKeys={expandedKeys}
          onExpandedChange={setExpandedKeys}
        >
          {connected.length > 0 && (
            <ListSection
              id="connected"
              title="Connected"
              count={connected.length}
              tooltip="Your active integrations"
            >
              <ScrollShadow className="max-h-[150px]">
                {connected.map((integration) => (
                  <IntegrationRow
                    key={integration.id}
                    integration={integration}
                    onConnect={connectIntegration}
                  />
                ))}
              </ScrollShadow>
            </ListSection>
          )}
          {suggestedIntegrations.length > 0 && (
            <ListSection
              id="suggested"
              title="Discover More"
              count={suggestedIntegrations.length}
              tooltip="Public integrations from the community marketplace"
            >
              <ScrollShadow className="max-h-[150px] divide-y divide-zinc-700">
                {suggestedIntegrations.map((suggestion) => (
                  <SuggestedIntegrationRow
                    key={suggestion.id}
                    suggestion={suggestion}
                    onConnected={refetch}
                  />
                ))}
              </ScrollShadow>
              <div className="mt-3 flex justify-center">
                <Link
                  href="/marketplace"
                  className={toneVariants({
                    tone: "accent",
                    className: "text-xs hover:underline gap-1",
                  })}
                >
                  <span>Go to Marketplace</span>
                  <ArrowRight02Icon width={16} height={16} />
                </Link>
              </div>
            </ListSection>
          )}
          {notConnected.length > 0 && (
            <ListSection
              id="available"
              title="Available"
              count={notConnected.length}
              tooltip="Integrations provided natively by GAIA"
            >
              <ScrollShadow className="max-h-[200px]">
                {notConnected.map((integration) => (
                  <IntegrationRow
                    key={integration.id}
                    integration={integration}
                    onConnect={connectIntegration}
                  />
                ))}
              </ScrollShadow>
            </ListSection>
          )}
        </Accordion>
      </div>
    </CollapsibleListWrapper>
  );
}

export { IntegrationListSection };
