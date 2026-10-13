// Serves the gaia-connect installer at heygaia.io/connect.sh:
//   curl -fsSL https://heygaia.io/connect.sh | sh -s -- --token <code>

import { serveInstallScript } from "@/lib/installScript";

export function GET(): Promise<Response> {
  return serveInstallScript({
    repoPath: "tools/gaia-connect/install.sh",
    name: "gaia-connect installer",
    fallbackCommand: "npx @heygaia/cli connect --token <code>",
  });
}
