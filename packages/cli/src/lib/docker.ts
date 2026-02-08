import { execa } from "execa";

export interface ContainerStatus {
  name: string;
  status: "running" | "stopped" | "not_found";
  health?: string;
}

const GAIA_CONTAINERS = [
  "gaia-backend",
  "chromadb",
  "postgres",
  "redis",
  "mongo",
  "rabbitmq",
  "arq_worker",
];

export async function getContainerStatuses(): Promise<ContainerStatus[]> {
  const results: ContainerStatus[] = [];

  for (const name of GAIA_CONTAINERS) {
    try {
      const { stdout } = await execa("docker", [
        "inspect",
        "--format",
        "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
        name,
      ]);
      const [status, health] = stdout.trim().split("|");
      results.push({
        name,
        status: status === "running" ? "running" : "stopped",
        health: health !== "none" ? health : undefined,
      });
    } catch {
      results.push({ name, status: "not_found" });
    }
  }

  return results;
}

export async function isDockerRunning(): Promise<boolean> {
  try {
    await execa("docker", ["info"]);
    return true;
  } catch {
    return false;
  }
}
