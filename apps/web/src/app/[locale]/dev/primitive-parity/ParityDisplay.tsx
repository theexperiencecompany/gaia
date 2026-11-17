"use client";

import {
  Accordion,
  Avatar,
  Card,
  Chip,
  Kbd,
  Pagination,
  ProgressBar,
  Separator,
  Skeleton,
  Spinner,
  Table,
  Tabs,
} from "@heroui/react";
import { accordionVariants } from "@/components/shared/accordionVariants";
import {
  chipVariants,
  tableVariants,
} from "@/components/shared/controlVariants";
import { shapeVariants } from "@/components/shared/shape";
import { tabsVariants } from "@/components/shared/tabsVariants";

import { ParityCell, ParitySection } from "./ParityCell";

type ChipColor = "default" | "accent" | "success" | "warning" | "danger";

const CHIPS: {
  id: string;
  color?: ChipColor;
  size?: "sm" | "md";
  className?: string;
}[] = [
  { id: "chip/flat-sm", size: "sm" },
  { id: "chip/flat-md", size: "md" },
  { id: "chip/flat-success-sm", color: "success", size: "sm" },
  { id: "chip/flat-primary-sm", color: "accent", size: "sm" },
  { id: "chip/flat-primary-md", color: "accent", size: "md" },
  { id: "chip/flat-warning-sm", color: "warning", size: "sm" },
  { id: "chip/flat-danger-sm", color: "danger", size: "sm" },
  {
    id: "chip/flat-secondary-sm",
    color: "accent",
    size: "sm",
    className: chipVariants({ hue: "secondary" }),
  },
  {
    id: "chip/flat-sm-radius-sm",
    size: "sm",
    className: shapeVariants({ shape: "sm" }),
  },
];

const TABS = [
  ["tabs/solid", tabsVariants({ variant: "solid" })],
  [
    "tabs/solid-sm-pill",
    tabsVariants({ variant: "solid", size: "sm", shape: "pill" }),
  ],
  [
    "tabs/solid-primary-pill",
    tabsVariants({ variant: "solid", color: "accent", shape: "pill" }),
  ],
  ["tabs/underlined", tabsVariants({ variant: "underlined" })],
  ["tabs/light-primary", tabsVariants({ variant: "light", color: "accent" })],
] as const;

const ACCORDIONS = [
  ["accordion/light", accordionVariants({ variant: "light" })],
  [
    "accordion/light-compact",
    accordionVariants({ variant: "light", density: "compact" }),
  ],
  ["accordion/shadow", accordionVariants({ variant: "shadow" })],
] as const;

/** Chips, tabs, accordions and the display primitives in v2's combinations, for the parity harness. */
export function ParityDisplay() {
  return (
    <>
      <ParitySection title="Chip">
        {CHIPS.map(({ id, color, size, className }) => (
          <ParityCell key={id} id={id}>
            <Chip
              variant="soft"
              color={color}
              size={size}
              className={className}
            >
              Chip
            </Chip>
          </ParityCell>
        ))}
      </ParitySection>
      <ParitySection title="Tabs">
        {TABS.map(([id, styles]) => (
          <ParityCell key={id} id={id}>
            <Tabs defaultSelectedKey="a" className={styles.base()}>
              <Tabs.List aria-label={id} className={styles.tabList()}>
                {["a", "b", "c"].map((key) => (
                  <Tabs.Tab key={key} id={key} className={styles.tab()}>
                    Tab {key}
                    <Tabs.Indicator className={styles.tabIndicator()} />
                  </Tabs.Tab>
                ))}
              </Tabs.List>
            </Tabs>
          </ParityCell>
        ))}
      </ParitySection>
      <ParitySection title="Accordion">
        {ACCORDIONS.map(([id, styles]) => (
          <ParityCell key={id} id={id} wide>
            <Accordion defaultExpandedKeys={["one"]} className={styles.base()}>
              {["one", "two"].map((key) => (
                <Accordion.Item key={key} id={key}>
                  <Accordion.Heading>
                    <Accordion.Trigger className={styles.trigger()}>
                      Item {key}
                      <Accordion.Indicator className={styles.indicator()} />
                    </Accordion.Trigger>
                  </Accordion.Heading>
                  <Accordion.Panel>
                    <div className={styles.content()}>Body {key}</div>
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          </ParityCell>
        ))}
      </ParitySection>
      <ParitySection title="Display">
        {(["sm", "md"] as const).map((size) => (
          <ParityCell key={size} id={`avatar/${size}`}>
            <Avatar size={size}>
              <Avatar.Fallback>AR</Avatar.Fallback>
            </Avatar>
          </ParityCell>
        ))}
        <ParityCell id="card/default" wide>
          <Card>
            <Card.Header>
              <Card.Title>Title</Card.Title>
            </Card.Header>
            <Card.Content>Body text</Card.Content>
          </Card>
        </ParityCell>
        <ParityCell id="divider/default" wide>
          <Separator />
        </ParityCell>
        <ParityCell id="skeleton/default">
          <Skeleton className="h-6 w-40" />
        </ParityCell>
        {(
          [
            ["spinner/sm", "sm", "accent"],
            ["spinner/md", "md", "accent"],
            ["spinner/lg", "lg", "accent"],
            ["spinner/current-sm", "sm", "current"],
          ] as const
        ).map(([id, size, color]) => (
          <ParityCell key={id} id={id}>
            <Spinner size={size} color={color} />
          </ParityCell>
        ))}
        <ParityCell id="kbd/default">
          <Kbd>
            <Kbd.Abbr keyValue="command" />K
          </Kbd>
        </ParityCell>
        {(["sm", "md"] as const).map((size) => (
          <ParityCell key={size} id={`progress/${size}`} wide>
            <ProgressBar aria-label="Progress" value={40} size={size}>
              <ProgressBar.Track>
                <ProgressBar.Fill />
              </ProgressBar.Track>
            </ProgressBar>
          </ParityCell>
        ))}
        <ParityCell id="pagination/faded">
          <Pagination>
            <Pagination.Content>
              <Pagination.Item>
                <Pagination.Previous>
                  <Pagination.PreviousIcon />
                </Pagination.Previous>
              </Pagination.Item>
              {[1, 2, 3].map((page) => (
                <Pagination.Item key={page}>
                  <Pagination.Link isActive={page === 2}>
                    {page}
                  </Pagination.Link>
                </Pagination.Item>
              ))}
              <Pagination.Item>
                <Pagination.Next>
                  <Pagination.NextIcon />
                </Pagination.Next>
              </Pagination.Item>
            </Pagination.Content>
          </Pagination>
        </ParityCell>
        <ParityCell id="table/default" wide>
          <Table className={tableVariants({ surface: "card" })}>
            <Table.Content aria-label="Table">
              <Table.Header>
                <Table.Column id="name" isRowHeader>
                  Name
                </Table.Column>
                <Table.Column id="role">Role</Table.Column>
              </Table.Header>
              <Table.Body>
                {["Ada", "Linus"].map((name) => (
                  <Table.Row key={name} id={name}>
                    <Table.Cell>{name}</Table.Cell>
                    <Table.Cell>Engineer</Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table.Content>
          </Table>
        </ParityCell>
      </ParitySection>
    </>
  );
}
