/**
 * Headers the Next server sends when it resolves a short link on a viewer's
 * behalf: who the viewer is, and proof (SHORTLINK_VIEWER_IP_SECRET, shared with
 * the API) that this server is the one saying so. Same names as
 * VIEWER_IP_HEADER / VIEWER_IP_PROOF_HEADER in apps/api/app/constants/http.py.
 */
export const VIEWER_IP_HEADER = "X-Gaia-Viewer-IP";
export const VIEWER_IP_PROOF_HEADER = "X-Gaia-Viewer-IP-Proof";
