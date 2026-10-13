// Serves the gaia-connect installer at heygaia.io/connect.sh:
//   curl -fsSL https://heygaia.io/connect.sh | sh -s -- --token <code>
// The script itself lives in the repo (tools/gaia-connect/install.sh) and is
// fetched from master so a fix ships without redeploying the web app.

const INSTALL_SCRIPT_URL =
  "https://raw.githubusercontent.com/theexperiencecompany/gaia/master/tools/gaia-connect/install.sh";

export async function GET(): Promise<Response> {
  const upstream = await fetch(INSTALL_SCRIPT_URL, {
    next: { revalidate: 300 },
  });

  // Never fall back to a stub: a script that "works" but isn't the installer
  // would be piped straight into a shell.
  if (!upstream.ok) {
    return new Response(
      `# Failed to fetch the gaia-connect installer (${upstream.status}).\n` +
        `# Install it with: npx @heygaia/cli connect --token <code>\n`,
      { status: 502, headers: { "Content-Type": "text/plain; charset=utf-8" } },
    );
  }

  return new Response(await upstream.text(), {
    headers: {
      "Content-Type": "text/x-shellscript; charset=utf-8",
      "Cache-Control": "public, max-age=300",
    },
  });
}
