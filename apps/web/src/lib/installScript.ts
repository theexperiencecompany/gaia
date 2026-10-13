// Installer scripts live in the repo and are fetched from master, so a fix
// ships without redeploying the web app.
const REPO_RAW_BASE =
  "https://raw.githubusercontent.com/theexperiencecompany/gaia/master";

const REVALIDATE_SECONDS = 300;

interface InstallScript {
  /** Repo-relative path of the script, e.g. "packages/cli/install.sh". */
  repoPath: string;
  /** Human name used in the failure message, e.g. "GAIA CLI installer". */
  name: string;
  /** Command the user can run instead when the script cannot be fetched. */
  fallbackCommand: string;
}

export async function serveInstallScript({
  repoPath,
  name,
  fallbackCommand,
}: InstallScript): Promise<Response> {
  const upstream = await fetch(`${REPO_RAW_BASE}/${repoPath}`, {
    next: { revalidate: REVALIDATE_SECONDS },
  });

  // Never fall back to a stub: a script that "works" but isn't the installer
  // would be piped straight into a shell.
  if (!upstream.ok) {
    return new Response(
      `# Failed to fetch the ${name} (${upstream.status}).\n` +
        `# Install it with: ${fallbackCommand}\n`,
      { status: 502, headers: { "Content-Type": "text/plain; charset=utf-8" } },
    );
  }

  return new Response(await upstream.text(), {
    headers: {
      "Content-Type": "text/x-shellscript; charset=utf-8",
      "Cache-Control": `public, max-age=${REVALIDATE_SECONDS}`,
    },
  });
}
