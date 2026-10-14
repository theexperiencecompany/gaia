/**
 * Whether this build fronts a self-hosted instance. apps/web/Dockerfile (the
 * self-host image) bakes NEXT_PUBLIC_GAIA_SELFHOST=true; hosted builds never
 * set it. Inlined at build time, so server, middleware and client all agree
 * from first paint without a request, and hosted pages stay static.
 */
export function isSelfhostWeb(): boolean {
  return process.env.NEXT_PUBLIC_GAIA_SELFHOST === "true";
}
