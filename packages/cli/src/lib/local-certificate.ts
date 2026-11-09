/**
 * Which `gaia up --domain` names get their certificate from Caddy's own local
 * authority instead of a public one, and where that authority's root is.
 * @module lib/local-certificate
 */

/**
 * Names reserved from the public DNS (RFC 2606, 6761, 6762, 8375, and ICANN's
 * .internal), which no public certificate authority will certify.
 */
const LOCAL_ONLY_SUFFIXES = [
  ".test",
  ".example",
  ".invalid",
  ".localhost",
  ".local",
  ".internal",
  ".home.arpa",
] as const;

/** Copies the local authority's root out of the proxy container, to trust it on a device. */
export const LOCAL_ROOT_COPY_COMMAND =
  "docker cp gaia-selfhost-proxy-1:/data/caddy/pki/authorities/local/root.crt gaia-root.crt";

/** True when the domain can only get a certificate from a local authority. */
export function needsLocalCertificate(domain: string): boolean {
  const name = domain.toLowerCase();
  return LOCAL_ONLY_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

/** Whether `gaia up` asks a public CA for the domain's certificate (not a local-CA name like gaia.test). */
export function needsPublicCertificate(
  domain: string | undefined,
): domain is string {
  return domain !== undefined && !needsLocalCertificate(domain);
}
