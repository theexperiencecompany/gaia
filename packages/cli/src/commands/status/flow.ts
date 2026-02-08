import type { CLIStore } from "../../ui/store.js";
import { checkAllServices, getDockerStatus } from "../../lib/healthcheck.js";

export async function runStatusFlow(store: CLIStore): Promise<void> {
  store.setStep("Checking");
  store.setStatus("Checking service health...");

  const [services, docker] = await Promise.all([
    checkAllServices(),
    getDockerStatus(),
  ]);

  store.updateData("services", services);
  store.updateData("docker", docker);

  const upCount = services.filter((s) => s.status === "up").length;
  const totalCount = services.length;

  store.setStep("Results");
  store.setStatus(`${upCount}/${totalCount} services running`);
}
