/**
 * The identities an analytics event may be attributed to, mirroring
 * `libs/shared/py/analytics/identity.py`. Both are branded so a plain string
 * (an email, "system", a raw platform handle) does not type-check as one.
 */

declare const userIdBrand: unique symbol;
declare const platformIdentityBrand: unique symbol;

/** GAIA's stable user id, the Mongo ObjectId of the users document. Build with `parseUserId`. */
export type UserId = string & { readonly [userIdBrand]: true };

/** `"<platform>:<platformUserId>"` for a bot user who has not linked yet. Build with `platformIdentity`. */
export type PlatformIdentity = string & {
  readonly [platformIdentityBrand]: true;
};

export type AnalyticsId = UserId | PlatformIdentity;
