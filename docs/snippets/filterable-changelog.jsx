import { useState, useEffect } from "react";

export const CHANGELOG_APPS = ["api", "web", "desktop", "mobile", "bots", "cli"];

export const FilterableChangelog = ({ children }) => {
  const [activeFilter, setActiveFilter] = useState("all");

  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent("changelog-filter", { detail: { filter: activeFilter } })
    );
  }, [activeFilter]);

  const pillStyle = (key) => ({
    padding: "5px 14px",
    borderRadius: "9999px",
    fontSize: "13px",
    fontWeight: 500,
    cursor: "pointer",
    border: "1px solid",
    borderColor: activeFilter === key ? "#00bbff" : "rgba(0,0,0,0.12)",
    backgroundColor: activeFilter === key ? "#00bbff" : "transparent",
    color: activeFilter === key ? "#fff" : "inherit",
    transition: "all 120ms ease",
    letterSpacing: key === "all" ? undefined : "0.04em",
    textTransform: key === "all" ? undefined : "uppercase",
  });

  return (
    <div>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "8px",
          marginBottom: "32px",
          position: "sticky",
          top: "0",
          zIndex: 10,
          paddingTop: "14px",
          paddingBottom: "14px",
          backdropFilter: "blur(8px)",
          WebkitBackdropFilter: "blur(8px)",
        }}
      >
        <button onClick={() => setActiveFilter("all")} style={pillStyle("all")}>
          All
        </button>
        {CHANGELOG_APPS.map((app) => (
          <button key={app} onClick={() => setActiveFilter(app)} style={pillStyle(app)}>
            {app}
          </button>
        ))}
      </div>
      {children}
    </div>
  );
};

export const AppSection = ({ app, children }) => {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const handler = (e) => {
      const filter = e.detail?.filter ?? "all";
      setVisible(filter === "all" || filter === app);
    };
    window.addEventListener("changelog-filter", handler);
    return () => window.removeEventListener("changelog-filter", handler);
  }, [app]);

  if (!visible) return null;

  return <div>{children}</div>;
};
