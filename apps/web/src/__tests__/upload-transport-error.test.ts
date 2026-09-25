import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/shared/RateLimitToast", () => ({
  showFeatureRestrictedToast: vi.fn(),
  showRateLimitToast: vi.fn(),
  showTokenLimitToast: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

import { toast } from "@/lib/toast";
import { processAxiosError } from "@/utils/interceptorUtils";

type InterceptedError = Parameters<typeof processAxiosError>[0];

const networkError = (data: unknown): InterceptedError =>
  ({ code: "ERR_NETWORK", config: { data } }) as unknown as InterceptedError;

describe("transport failure copy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names file size, not reachability, when a file upload gets no response", () => {
    const form = new FormData();
    form.append("file", new Blob(["x"]), "big.pdf");
    const error = networkError(form);

    processAxiosError(error, { router: {} as never });

    expect(toast.error).toHaveBeenCalledWith(
      "Upload failed. The file may be too large. Try a smaller file.",
    );
    expect(error.handled).toBe(true);
  });

  it("keeps the reachability message for a request without a file body", () => {
    const error = networkError('{"name":"x"}');

    processAxiosError(error, { router: {} as never });

    expect(toast.error).toHaveBeenCalledWith(
      "Server unreachable. Try again later",
    );
    expect(error.handled).toBe(true);
  });
});
