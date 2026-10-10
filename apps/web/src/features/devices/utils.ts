import {
  PAIRING_CODE_GROUP_LENGTH,
  PAIRING_CODE_LENGTH,
  PAIRING_CODE_SEPARATOR,
} from "./constants";

/**
 * Normalize a raw pairing code (from the `?code=` param or a paste) into the
 * separator-less, uppercase digits the code field holds. Strips the separator
 * the daemon prints (e.g. "NS2V-YC5S" -> "NS2VYC5S") so a code copied straight
 * from chat pastes cleanly.
 */
export function normalizePairingCode(raw: string): string {
  return raw
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, PAIRING_CODE_LENGTH);
}

/**
 * Re-insert the separator the approve API expects (e.g. "NS2VYC5S" ->
 * "NS2V-YC5S"). Input is the separator-less digits from normalizePairingCode.
 */
export function toApiPairingCode(digits: string): string {
  return `${digits.slice(0, PAIRING_CODE_GROUP_LENGTH)}${PAIRING_CODE_SEPARATOR}${digits.slice(PAIRING_CODE_GROUP_LENGTH)}`;
}
