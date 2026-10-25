import * as fs from "fs";
import * as path from "path";
import {
  runConcurrentInteractiveCommands,
  runInteractiveCommand,
} from "../../lib/child-process.js";
import {
  DEV_LOG_FILE,
  isPidAlive,
  readStoredDevPid,
} from "../../lib/dev-processes.js";
import {
  portOverridesToDockerEnv,
  readDockerComposePortOverrides,
} from "../../lib/env-writer.js";
import { detectSetupMode, findInstallRoot } from "../../lib/install-root.js";
import {
  composeFileArgs,
  selfhostComposeFiles,
} from "../../lib/service-starter.js";
import { printHeader } from "../../ui/header/header-lines.js";

function getDockerEnvFileArgs(dockerDir: string): string[] {
  const envPath = path.join(dockerDir, ".env");
  if (fs.existsSync(envPath)) {
    return ["--env-file", ".env"];
  }
  return [];
}

function out(line: string): void {
  process.stdout.write(`${line}\n`);
}

export async function runLogs(): Promise<void> {
  await printHeader({ showStatus: false });
  const repoPath = findInstallRoot();
  if (!repoPath) {
    throw new Error(
      "GAIA isn't installed here, so it has no logs yet.\nInstall it with 'gaia up'.",
    );
  }

  const setupMode = await detectSetupMode(repoPath);
  if (!setupMode) {
    throw new Error(
      "This GAIA install isn't set up yet, so it has no logs.\nFinish it with 'gaia up'.",
    );
  }
  out("  Following GAIA's logs. Ctrl-C stops.");
  out("");

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
        ...composeFileArgs(selfhostComposeFiles()),
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
    out("  App and infrastructure logs:");
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

  out(
    "  'gaia dev' isn't running, so these are the Docker services' logs only.",
  );
  await runInteractiveCommand("docker", dockerArgs, dockerDir, dockerEnv);
}
