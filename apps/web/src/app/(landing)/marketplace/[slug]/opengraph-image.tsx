import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Integration";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

interface Props {
  params: Promise<{ slug: string }>;
}

export default async function Image({ params }: Props) {
  const { slug } = await params;

  const apiUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
  const baseUrl = apiUrl.replace(/\/$/, "");

  // Fetch integration data
  let integration;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const response = await fetch(`${baseUrl}/integrations/public/${slug}`, {
      next: { revalidate: 3600 },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      integration = await response.json();
    }
  } catch {
    integration = null;
  }

  // Fallback if integration not found
  if (!integration) {
    return new ImageResponse(
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #111111 0%, #1a1a1a 100%)",
          color: "white",
          fontSize: 48,
          fontFamily: "sans-serif",
        }}
      >
        Integration Not Found
      </div>,
      { ...size },
    );
  }

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: "linear-gradient(135deg, #111111 0%, #1a1a1a 100%)",
        padding: 60,
        fontFamily: "sans-serif",
      }}
    >
      {/* Top section: Category chip + GAIA branding */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div
          style={{
            background: "#00bbff20",
            color: "#00bbff",
            padding: "8px 16px",
            borderRadius: 9999,
            fontSize: 18,
          }}
        >
          {integration.category}
        </div>
        <div
          style={{
            color: "#ffffff",
            fontSize: 24,
            fontWeight: 700,
            letterSpacing: 2,
          }}
        >
          GAIA
        </div>
      </div>

      {/* Center: Icon + Name */}
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          gap: 32,
        }}
      >
        {integration.iconUrl && (
          <img
            src={integration.iconUrl}
            width={120}
            height={120}
            style={{ borderRadius: 24 }}
          />
        )}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              fontSize: 64,
              fontWeight: 700,
              color: "white",
              lineHeight: 1.1,
            }}
          >
            {integration.name}
          </div>
          <div
            style={{
              fontSize: 24,
              color: "#a3a3a3",
              maxWidth: 700,
              marginTop: 16,
              lineHeight: 1.4,
            }}
          >
            {integration.description?.slice(0, 120)}
            {integration.description?.length > 120 ? "..." : ""}
          </div>
        </div>
      </div>

      {/* Bottom: Stats */}
      <div
        style={{
          display: "flex",
          gap: 40,
          color: "#71717a",
          fontSize: 20,
        }}
      >
        <div>{integration.toolCount} tools</div>
        <div>{integration.cloneCount} clones</div>
        <div>by {integration.creator?.name}</div>
      </div>
    </div>,
    { ...size },
  );
}
