/**
 * What `gaia status` says, as data the Ink screen and the plain printer both
 * render: one headline (running, not running, or why Docker can't be used),
 * then one row per group with a mark per part, then where GAIA is installed.
 * @module commands/status/report
 */

import { dependencyName, serviceName } from "../../lib/display-names.js";
import type { ContainerStatus } from "../../lib/docker.js";
import type { DockerStatus } from "../../lib/healthcheck.js";
import type {
  StatusFacts,
  StatusItem,
  StatusReport,
  StatusRow,
} from "./report.types.js";

/** Compose services that make up the app itself, in the order a person thinks of them. */
const APP_SERVICES = ["gaia-web", "gaia-backend", "arq_worker", "proxy"];
const DATA_SERVICES = ["mongo", "postgres", "redis", "rabbitmq", "chromadb"];

function row(label: string, items: StatusItem[], fix: string): StatusRow {
  const down = items.some((item) => !item.ok);
  return down
    ? { label, items, note: fix, tone: "fail" }
    : { label, items, tone: "ok" };
}

function containerItems(
  containers: ContainerStatus[],
  services: readonly string[],
): StatusItem[] {
  return services
    .map((service) => containers.find((c) => c.name === service))
    .filter((c): c is ContainerStatus => c !== undefined)
    .map((c) => ({ ok: c.status === "running", name: serviceName(c.name) }));
}

function dataRow(facts: StatusFacts, containers: ContainerStatus[]): StatusRow {
  const readiness = facts.readiness;
  const items =
    readiness?.reachable === true
      ? readiness.dependencies.map((d) => ({
          ok: d.ok,
          name: dependencyName(d.name),
        }))
      : containerItems(containers, DATA_SERVICES);
  const firstFix =
    readiness?.reachable === true
      ? readiness.dependencies.find((d) => !d.ok)?.fix
      : undefined;
  return row("Data", items, firstFix ?? "See why with: gaia doctor");
}

function botsRow(containers: ContainerStatus[]): StatusRow {
  const bots = containers.filter((c) => c.name.startsWith("bot-"));
  if (bots.length === 0) {
    return {
      label: "Bots",
      items: [],
      note: "none · add one: gaia bots add telegram",
      tone: "dim",
    };
  }
  return row(
    "Bots",
    bots.map((c) => ({
      ok: c.status === "running",
      name: serviceName(c.name),
    })),
    "See why with: gaia doctor",
  );
}

function setupRow(facts: StatusFacts): StatusRow | null {
  if (facts.setupComplete === null) return null;
  if (facts.setupComplete) {
    return { label: "Setup", items: [], note: "finished", tone: "ok" };
  }
  return {
    label: "Setup",
    items: [],
    note: `not finished · open ${facts.webUrl}/setup`,
    tone: "warn",
  };
}

function selfhostReport(
  facts: StatusFacts,
  docker: DockerStatus,
): StatusReport {
  const containers = docker.containers;
  const app = row(
    "App",
    containerItems(containers, APP_SERVICES),
    "Start it: gaia start",
  );
  const rows = [app, dataRow(facts, containers), botsRow(containers)];
  const setup = setupRow(facts);
  if (setup) rows.push(setup);
  const running = containers.some((c) => c.status === "running");
  const unhealthy = rows.some((r) => r.tone === "fail");
  if (!running) {
    return {
      headline: {
        kind: "fail",
        text: "GAIA isn't running · start it: gaia start",
      },
      rows: [],
      unhealthy: true,
    };
  }
  return {
    headline: unhealthy
      ? { kind: "fail", text: "GAIA is running, but part of it is down" }
      : { kind: "ok", text: "GAIA is running", url: facts.webUrl },
    rows,
    unhealthy,
  };
}

function developerReport(facts: StatusFacts): StatusReport {
  const items = facts.services.map((s) => ({
    ok: s.status === "up",
    name: `${s.name} :${s.port}`,
  }));
  const local = row("Local", items, "Start them: gaia dev");
  return {
    headline:
      local.tone === "fail"
        ? { kind: "fail", text: "Part of the dev stack is down" }
        : { kind: "ok", text: "The dev stack is running", url: facts.webUrl },
    rows: [local],
    unhealthy: local.tone === "fail",
  };
}

export function buildStatusReport(facts: StatusFacts): StatusReport {
  if (!facts.installed) {
    return {
      headline: { kind: "warn", text: `${facts.install} · run: gaia up` },
      rows: [],
      unhealthy: true,
    };
  }
  const docker = facts.docker;
  if (docker?.problem) {
    // GAIA may well be running: this terminal just cannot ask Docker. Its API
    // still answers over HTTP, so say what is known and how to see the rest.
    const answering = facts.readiness?.reachable === true;
    const dockerRow: StatusRow = {
      label: "Docker",
      items: [],
      note: docker.problem.state,
      tone: "warn",
    };
    const setup = setupRow(facts);
    return {
      headline: answering
        ? { kind: "ok", text: "GAIA is running", url: facts.webUrl }
        : { kind: "fail", text: docker.problem.summary },
      hint: docker.problem.fix,
      rows: answering
        ? [dataRow(facts, []), ...(setup ? [setup] : []), dockerRow]
        : [],
      unhealthy: true,
    };
  }
  if (facts.services.length > 0) return developerReport(facts);
  return selfhostReport(facts, docker ?? { access: "ready", containers: [] });
}
