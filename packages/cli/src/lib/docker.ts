import { execa } from "execa";

export interface ContainerStatus {
  name: string;
  status: "running" | "stopped" | "not_found";
  health?: string;
}

const GAIA_CONTAINERS = [
  "gaia-backend",
  "gaia-web",
  "chromadb",
  "postgres",
  "redis",
  "mongo",
  "rabbitmq",
  "arq_worker",
];

export async function getContainerStatuses(): Promise<ContainerStatus[]> {
  try {
    const { stdout } = await execa("docker", [
      "inspect",
      "--format",
      "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
      ...GAIA_CONTAINERS,
    ]);

    const inspected = new Map<string, ContainerStatus>();
    for (const line of stdout.trim().split("\n")) {
      if (!line) continue;
      const [rawName, status, health] = line.split("|");
      const name = rawName?.replace(/^\//, "") ?? "";
      inspected.set(name, {
        name,
        status: status === "running" ? "running" : "stopped",
        health: health !== "none" ? health : undefined,
      });
    }

    return GAIA_CONTAINERS.map(
      (name) => inspected.get(name) ?? { name, status: "not_found" },
    );
  } catch {
    const promises = GAIA_CONTAINERS.map(
      async (name): Promise<ContainerStatus> => {
        try {
          const { stdout } = await execa("docker", [
            "inspect",
            "--format",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            name,
          ]);
          const [status, health] = stdout.trim().split("|");
          return {
            name,
            status: status === "running" ? "running" : "stopped",
            health: health !== "none" ? health : undefined,
          };
        } catch {
          return { name, status: "not_found" };
        }
      },
    );

    return Promise.all(promises);
  }
}

export async function isDockerRunning(): Promise<boolean> {
  try {
    await execa("docker", ["info"]);
    return true;
  } catch {
    return false;
  }
}
