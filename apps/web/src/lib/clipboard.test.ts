// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText, copyWithFeedback } from "@/lib/clipboard";

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast: { error: toastError } }));

function withoutClipboardApi() {
  vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("copyText", () => {
  it("writes through the Clipboard API when the context is secure", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    document.execCommand = vi.fn(() => true);

    await copyText("https://gaia.local/x");

    expect(writeText).toHaveBeenCalledWith("https://gaia.local/x");
    expect(document.execCommand).not.toHaveBeenCalled();
  });

  it("copies the exact text through a selection on a plain-http origin", async () => {
    withoutClipboardApi();
    let selectedAtCopy = "";
    document.execCommand = vi.fn(() => {
      selectedAtCopy = document.getSelection()?.toString() ?? "";
      return true;
    });

    await copyText("line one\n  line two");

    expect(document.execCommand).toHaveBeenCalledWith("copy");
    expect(selectedAtCopy).toBe("line one\n  line two");
    expect(document.body.childElementCount).toBe(0);
  });

  it("falls back when the Clipboard API refuses permission", async () => {
    const writeText = vi.fn(() => Promise.reject(new Error("NotAllowedError")));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    document.execCommand = vi.fn(() => true);

    await copyText("code");

    expect(document.execCommand).toHaveBeenCalledWith("copy");
  });

  it("restores the user's selection after copying", async () => {
    withoutClipboardApi();
    document.body.innerHTML = "<p>keep me selected</p>";
    const paragraph = document.querySelector("p") as HTMLParagraphElement;
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    document.getSelection()?.addRange(range);
    document.execCommand = vi.fn(() => true);

    await copyText("other");

    expect(document.getSelection()?.toString()).toBe("keep me selected");
  });

  it("rejects when the browser refuses every copy path", async () => {
    withoutClipboardApi();
    document.execCommand = vi.fn(() => false);

    await expect(copyText("x")).rejects.toThrow(/refused/);
  });
});

describe("copyWithFeedback", () => {
  it("tells the user when nothing could be copied", async () => {
    toastError.mockClear();
    withoutClipboardApi();
    document.execCommand = vi.fn(() => false);

    expect(await copyWithFeedback("x")).toBe(false);
    expect(toastError).toHaveBeenCalledOnce();
  });

  it("reports success without a toast", async () => {
    toastError.mockClear();
    withoutClipboardApi();
    document.execCommand = vi.fn(() => true);

    expect(await copyWithFeedback("x")).toBe(true);
    expect(toastError).not.toHaveBeenCalled();
  });
});
