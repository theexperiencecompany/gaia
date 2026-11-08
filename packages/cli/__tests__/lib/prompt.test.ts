import { afterEach, describe, expect, it, vi } from "vitest";
import { askSecret, maskSecret } from "../../src/lib/prompt.js";

describe("maskSecret", () => {
  it("shows a long token's last four characters so a paste can be checked", () => {
    expect(maskSecret("123456:ABCdefGHI")).toBe("••••••••••••fGHI");
  });

  it("hides a short secret entirely", () => {
    expect(maskSecret("abcd1234")).toBe("••••••••");
  });
});

describe("askSecret in a terminal", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(process.stdin, "isTTY");
  });

  it("cancels on Esc the way Ctrl-C does: nothing changed, exit 130", async () => {
    Object.defineProperty(process.stdin, "isTTY", {
      value: true,
      configurable: true,
    });
    process.stdin.setRawMode = vi.fn(() => process.stdin);
    let text = "";
    vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
      text += String(chunk);
      return true;
    });
    const exited = new Promise<number | undefined>((resolve) => {
      vi.spyOn(process, "exit").mockImplementation(((code?: number) => {
        resolve(code);
      }) as typeof process.exit);
    });

    void askSecret("Telegram bot token");
    process.stdin.emit("data", Buffer.from("\u001b"));

    expect(await exited).toBe(130);
    expect(text).toContain("■ Cancelled · nothing changed.");
  });
});
