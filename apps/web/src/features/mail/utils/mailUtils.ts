export function parseEmail(from: string | undefined): {
  name: string;
  email: string;
} {
  if (!from)
    return {
      name: "",
      email: "",
    };

  const match = from.match(/^(.*?)\s*<(.+?)>$/) || from.match(/(.+)/);

  if (match) {
    return {
      name: match[1] ? match[1].trim().replace(/^"|"$/g, "") : "",
      email: match[2] || "",
    };
  }

  return {
    name: "",
    email: from,
  };
}
