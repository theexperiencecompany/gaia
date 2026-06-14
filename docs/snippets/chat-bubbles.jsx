export const Chat = ({ messages = [] }) => {
  const css = `
.docs-imsg-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 1.25rem 0;
}
.docs-imsg-bubble {
  word-wrap: break-word;
  line-height: 24px;
  position: relative;
  padding: 8px 20px;
  max-width: 85%;
  border-radius: 20px;
  font-size: 0.875rem;
  white-space: pre-line;
}
.docs-imsg-bubble::before {
  content: "";
  position: absolute;
  bottom: 0;
  width: 20px;
  height: 18px;
}
.docs-imsg-from-them {
  background: #27272a;
  color: #fafafa;
  align-self: flex-start;
}
.docs-imsg-from-them::before {
  left: -7px;
  background-color: #27272a;
  clip-path: path("M 20 0 L 20 2 A 16 16 0 0 1 4 18 L 0 18 L 0 17.54 A 10 10 0 0 0 7 8 L 7 0 Z");
}
.docs-imsg-from-me {
  color: black;
  background: #00bbff;
  align-self: flex-end;
}
.docs-imsg-from-me::before {
  right: -7px;
  background-color: #00bbff;
  clip-path: path("M 0 0 L 0 2 A 16 16 0 0 0 16 18 L 20 18 L 20 17.54 A 10 10 0 0 1 13 8 L 13 0 Z");
}
.docs-imsg-no-tail::before {
  display: none;
}
.docs-imsg-group-gap {
  margin-top: 8px;
}
`;

  return (
    <div className="docs-imsg-list not-prose">
      <style>{css}</style>
      {messages.map((msg, idx) => {
        const from = msg.from === "user" ? "me" : "them";
        const next = messages[idx + 1];
        const prev = messages[idx - 1];
        const lastOfGroup = !next || next.from !== msg.from;
        const newGroup = prev && prev.from !== msg.from;
        const classes = [
          "docs-imsg-bubble",
          `docs-imsg-from-${from}`,
          lastOfGroup ? "" : "docs-imsg-no-tail",
          newGroup ? "docs-imsg-group-gap" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <div key={idx} className={classes}>
            {msg.text}
          </div>
        );
      })}
    </div>
  );
};
