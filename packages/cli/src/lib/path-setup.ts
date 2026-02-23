import { execSync } from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

interface PathSetupResult {
  success: boolean;
  message: string;
  inPath: boolean;
  pathAdded: boolean;
}

const isWindows = process.platform === "win32";

function tryExec(cmd: string): string | null {
  try {
    return execSync(cmd, {
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch {
    return null;
  }
}

function getNpmBinDir(): string | null {
  const prefix = tryExec("npm config get prefix");
  if (!prefix) return null;
  return isWindows ? prefix : path.join(prefix, "bin");
}

function getPnpmBinDir(): string | null {
  const binDir = tryExec("pnpm bin -g");
  if (binDir && fs.existsSync(binDir)) return binDir;

  const root = tryExec("pnpm root -g");
  if (root) {
    const candidate = path.join(path.dirname(root), "bin");
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function getBunBinDir(): string | null {
  const bunBin = path.join(os.homedir(), ".bun", "bin");
  if (fs.existsSync(bunBin)) return bunBin;
  return null;
}

function getYarnBinDir(): string | null {
  const binDir = tryExec("yarn global bin");
  if (binDir && fs.existsSync(binDir)) return binDir;
  return null;
}

function findGaiaBinDir(): string | null {
  const gaiaBin = isWindows ? "gaia.cmd" : "gaia";

  for (const getter of [
    getNpmBinDir,
    getPnpmBinDir,
    getBunBinDir,
    getYarnBinDir,
  ]) {
    const dir = getter();
    if (dir && fs.existsSync(path.join(dir, gaiaBin))) return dir;
  }

  // Also check plain "gaia" on Windows (some PMs use extensionless files)
  if (isWindows) {
    for (const getter of [
      getNpmBinDir,
      getPnpmBinDir,
      getBunBinDir,
      getYarnBinDir,
    ]) {
      const dir = getter();
      if (dir && fs.existsSync(path.join(dir, "gaia"))) return dir;
    }
  }

  return null;
}

function isGaiaInPath(): boolean {
  try {
    const cmd = isWindows ? "where gaia" : "command -v gaia";
    execSync(cmd, { stdio: ["pipe", "pipe", "pipe"] });
    return true;
  } catch {
    return false;
  }
}

function getShellRcFile(): string | null {
  const shell = process.env.SHELL || "";
  const home = os.homedir();

  if (shell.includes("zsh")) return path.join(home, ".zshrc");
  if (shell.includes("bash")) {
    const bashrc = path.join(home, ".bashrc");
    const profile = path.join(home, ".bash_profile");
    return fs.existsSync(bashrc) ? bashrc : profile;
  }
  if (shell.includes("fish"))
    return path.join(home, ".config", "fish", "config.fish");

  return null;
}

function addToRcFile(binDir: string, rcFile: string): boolean {
  try {
    const content = fs.existsSync(rcFile)
      ? fs.readFileSync(rcFile, "utf-8")
      : "";

    if (content.includes(binDir)) return true;

    const isFish = rcFile.includes("fish");
    const exportLine = isFish
      ? `\nset -gx PATH "${binDir}" $PATH  # Added by GAIA CLI\n`
      : `\nexport PATH="${binDir}:$PATH"  # Added by GAIA CLI\n`;

    fs.appendFileSync(rcFile, exportLine);
    return true;
  } catch {
    return false;
  }
}

function addToWindowsPath(binDir: string): boolean {
  try {
    // Update persistent user PATH via setx
    const currentPath = tryExec(
      "powershell -Command \"[Environment]::GetEnvironmentVariable('Path', 'User')\"",
    );
    if (currentPath?.includes(binDir)) return true;

    execSync(`setx PATH "${binDir};${currentPath || ""}"`, {
      stdio: ["pipe", "pipe", "pipe"],
    });

    // Also try to append to PowerShell profile
    const psProfile = path.join(
      os.homedir(),
      "Documents",
      "PowerShell",
      "Microsoft.PowerShell_profile.ps1",
    );
    const psProfileDir = path.dirname(psProfile);
    if (!fs.existsSync(psProfileDir)) {
      fs.mkdirSync(psProfileDir, { recursive: true });
    }
    const psContent = fs.existsSync(psProfile)
      ? fs.readFileSync(psProfile, "utf-8")
      : "";
    if (!psContent.includes(binDir)) {
      fs.appendFileSync(
        psProfile,
        `\n$env:Path = "${binDir};" + $env:Path  # Added by GAIA CLI\n`,
      );
    }

    return true;
  } catch {
    return false;
  }
}

export async function ensureGaiaInPath(): Promise<PathSetupResult> {
  if (isGaiaInPath()) {
    return {
      success: true,
      message: "gaia command is ready.",
      inPath: true,
      pathAdded: false,
    };
  }

  const binDir = findGaiaBinDir();
  if (!binDir) {
    return {
      success: false,
      message:
        "Could not find gaia binary. Run manually: npm install -g @heygaia/cli",
      inPath: false,
      pathAdded: false,
    };
  }

  if (isWindows) {
    const added = addToWindowsPath(binDir);
    if (added) {
      return {
        success: true,
        message:
          "Added to PATH. Restart your terminal for the 'gaia' command to be available.",
        inPath: false,
        pathAdded: true,
      };
    }
    return {
      success: false,
      message: `Add to your PATH manually: setx PATH "${binDir};%PATH%"`,
      inPath: false,
      pathAdded: false,
    };
  }

  const rcFile = getShellRcFile();
  if (!rcFile) {
    return {
      success: false,
      message: `Add to your PATH: export PATH="${binDir}:$PATH"`,
      inPath: false,
      pathAdded: false,
    };
  }

  const added = addToRcFile(binDir, rcFile);
  if (added) {
    const rcName = path.basename(rcFile);
    return {
      success: true,
      message: `Added to PATH via ~/${rcName}. Restart terminal or run: source ~/${rcName}`,
      inPath: false,
      pathAdded: true,
    };
  }

  return {
    success: false,
    message: `Could not write to ${rcFile}. Add manually: export PATH="${binDir}:$PATH"`,
    inPath: false,
    pathAdded: false,
  };
}
