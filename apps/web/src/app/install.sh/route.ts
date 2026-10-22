// Serves the GAIA CLI installer at heygaia.io/install.sh:
//   curl -fsSL https://heygaia.io/install.sh | sh

import { serveInstallScript } from "@/lib/installScript";

export function GET(): Promise<Response> {
  return serveInstallScript({
    repoPath: "packages/cli/install.sh",
    name: "GAIA CLI installer",
    fallbackCommand: "npm install -g @heygaia/cli",
  });
}
