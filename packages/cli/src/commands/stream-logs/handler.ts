import * as fs from "fs";
import * as path from "path";
import {
  portOverridesToDockerEnv,
  readDockerComposePortOverrides,
} from "../../lib/env-writer.js";
import {
  DEV_LOG_FILE,
  detectSetupMode,
  findRepoRoot,
  isPidAlive,
  readStoredDevPid,
} from "../../lib/service-starter.js";
import {
  runConcurrentInteractiveCommands,
  runInteractiveCommand,
} from "../../lib/interactive.js";

function getDockerEnvFileArgs(dockerDir: string): string[] {
  const envPath = path.join(dockerDir, ".env");
  if (fs.existsSync(envPath)) {
    return ["--env-file", ".env"];
  }
  return [];
}

export async function runLogs(): Promise<void> {
  const repoPath = findRepoRoot();
  if (!repoPath) {
    throw new Error(
      "Could not find GAIA repository. Run from within a cloned gaia repo.",
    );
  }

  const setupMode = await detectSetupMode(repoPath);
  if (!setupMode) {
    throw new Error(
      "No .env file found. Run 'gaia init' for fresh setup, or 'gaia setup' to configure an existing repo.",
    );
  }

  const dockerDir = path.join(repoPath, "infra", "docker");
  const envArgs = getDockerEnvFileArgs(dockerDir);
  const portOverrides = readDockerComposePortOverrides(repoPath);
  const dockerEnv =
    Object.keys(portOverrides).length > 0
      ? portOverridesToDockerEnv(portOverrides)
      : undefined;

  if (setupMode === "selfhost") {
    await runInteractiveCommand(
      "docker",
      [
        "compose",
        "-f",
        "docker-compose.selfhost.yml",
        ...envArgs,
        "logs",
        "-f",
        "--tail",
        "200",
      ],
      dockerDir,
      dockerEnv,
    );
    return;
  }

  const dockerArgs = ["compose", ...envArgs, "logs", "-f", "--tail", "200"];
  const devLogPath = path.join(repoPath, DEV_LOG_FILE);
  const devPid = readStoredDevPid(repoPath);
  const isDeveloperProcessAlive =
    typeof devPid === "number" && isPidAlive(devPid);

  if (fs.existsSync(devLogPath) && isDeveloperProcessAlive) {
    console.log("Streaming app and infrastructure logs...");
    if (process.platform === "win32") {
      await runConcurrentInteractiveCommands([
        {
          cmd: "powershell",
          args: [
            "-Command",
            `Get-Content -Path '${devLogPath.replace(/'/g, "''")}' -Wait -Tail 200`,
          ],
          cwd: repoPath,
        },
        {
          cmd: "docker",
          args: dockerArgs,
          cwd: dockerDir,
          env: dockerEnv,
        },
      ]);
    } else {
      await runConcurrentInteractiveCommands([
        {
          cmd: "tail",
          args: ["-n", "200", "-f", devLogPath],
          cwd: repoPath,
        },
        {
          cmd: "docker",
          args: dockerArgs,
          cwd: dockerDir,
          env: dockerEnv,
        },
      ]);
    }
    return;
  }

  if (fs.existsSync(devLogPath) && !isDeveloperProcessAlive) {
    console.log(
      "Detected stale developer app logs from a previous run. Streaming Docker logs only.",
    );
  }

  console.log(
    "No active developer process detected. Streaming Docker service logs. Run `gaia dev` in another terminal for live Nx app logs.",
  );
  await runInteractiveCommand("docker", dockerArgs, dockerDir, dockerEnv);
}
