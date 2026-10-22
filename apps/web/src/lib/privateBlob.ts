/** Path of the self-host blob route (LOCAL_BLOB_URL_PREFIX in apps/api/app/constants/files.py). */
const PRIVATE_BLOB_PATH_PREFIX = "/api/v1/blobs/";

/**
 * True for a self-hosted, session-authenticated blob URL. next/image must load
 * these unoptimized: its optimizer fetches without the user's cookie and would
 * cache a private file under a URL anyone can request.
 */
export function isPrivateBlobUrl(src: string | null | undefined): boolean {
  return Boolean(src?.startsWith(PRIVATE_BLOB_PATH_PREFIX));
}
