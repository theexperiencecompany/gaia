import { colors } from "../lib";
import { TICKET_TOP } from "./ticketTheme";

/** The referrer's photo on the invite card, or their initial when they have none. */
export function ReferrerFace({
  name,
  picture,
}: {
  name: string;
  picture: string | null;
}) {
  if (picture) {
    return (
      // biome-ignore lint/performance/noImgElement: Satori renders plain img, next/image does not exist here.
      <img
        src={picture}
        alt=""
        width={60}
        height={60}
        style={{ borderRadius: 999, objectFit: "cover" }}
      />
    );
  }
  return (
    <div
      style={{
        width: 60,
        height: 60,
        borderRadius: 999,
        backgroundColor: TICKET_TOP,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 28,
        color: colors.mutedLighter,
      }}
    >
      {name.charAt(0).toUpperCase()}
    </div>
  );
}
