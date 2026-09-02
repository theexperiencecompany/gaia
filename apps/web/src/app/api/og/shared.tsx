import { colors, fonts, OG_HEIGHT, OG_WIDTH } from "./lib";

export function CategoryBadge({ label }: { label: string }) {
  return (
    <div
      style={{
        backgroundColor: colors.accentBg,
        color: colors.accent,
        padding: "12px 28px",
        borderRadius: 999,
        fontSize: 22,
        fontWeight: 500,
        fontFamily: fonts.sans,
        display: "flex",
        backdropFilter: "blur(5px)",
      }}
    >
      {label}
    </div>
  );
}

export function HeroLayout({
  title,
  subtitle,
  backgroundImage,
}: {
  title: string;
  subtitle: string;
  backgroundImage: string;
}) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        position: "relative",
        fontFamily: fonts.sans,
      }}
    >
      {/* biome-ignore lint/performance/noImgElement: Using img for OG image generation (not Next.js context) */}
      <img
        src={backgroundImage}
        alt=""
        aria-hidden="true"
        width={OG_WIDTH}
        height={OG_HEIGHT}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: "bottom",
        }}
      />

      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background:
            "linear-gradient(180deg, rgba(9,9,11,0.1) 0%, rgba(9,9,11,0.3) 70%, rgba(9,9,11,0.7) 100%)",
        }}
      />

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          flex: 1,
          padding: 60,
          position: "relative",
          zIndex: "1",
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div
            style={{
              fontSize: 108,
              fontWeight: 400,
              color: colors.white,
              fontFamily: fonts.serif,
            }}
          >
            {title}
          </div>
          <div
            style={{
              fontSize: 32,
              color: colors.white,
              fontWeight: 500,
              fontFamily: fonts.sans,
              textAlign: "center",
              maxWidth: 900,
            }}
          >
            {subtitle}
          </div>
        </div>
      </div>
    </div>
  );
}
