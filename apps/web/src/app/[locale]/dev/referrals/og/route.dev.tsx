import { renderInviteOgImage } from "@/app/api/og/invite/inviteOgImage";
import { COPY_VARIANTS, FIXTURE_ME, FIXTURE_RESOLVE } from "../fixtures";

/** Renders the real invite OG image from gallery fixtures, so it can be previewed without the API. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const copyVariant =
    COPY_VARIANTS.find((v) => v === url.searchParams.get("copy")) ?? "gift";
  const invite =
    url.searchParams.get("fixture") === "photo"
      ? FIXTURE_RESOLVE.photo
      : FIXTURE_RESOLVE.valid;
  return renderInviteOgImage({
    invite,
    code: FIXTURE_ME.mid.code,
    copyVariant,
    baseUrl: url.origin,
  });
}
