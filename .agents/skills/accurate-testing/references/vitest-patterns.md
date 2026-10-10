# Vitest/Jest Patterns for Accurate Tests

## Table of Contents

1. [Module Mocking](#module-mocking)
2. [Type-Safe Mocks](#type-safe-mocks)
3. [Testing React Components](#testing-react-components)
4. [Testing API Routes](#testing-api-routes)
5. [Async Patterns](#async-patterns)
6. [Cleanup and Isolation](#cleanup-and-isolation)

---

## Module Mocking

### Mock External Modules, Not Internal Logic

```typescript
// WRONG — mocks the module you're testing
vi.mock("./userService", () => ({
  getUser: vi.fn().mockResolvedValue({ id: 1, name: "Alice" }),
}));

// RIGHT — mock the dependency of the module you're testing
vi.mock("@/lib/db", () => ({
  query: vi.fn(),
}));

import { getUser } from "./userService"; // real code
import { query } from "@/lib/db"; // mocked

test("getUser fetches from database", async () => {
  vi.mocked(query).mockResolvedValue([{ id: 1, name: "Alice" }]);
  const user = await getUser(1);
  expect(user.name).toBe("Alice");
});
```

### Partial Mocks (Keep Real Exports)

```typescript
vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual("@/lib/utils");
  return {
    ...actual,
    fetchExternalData: vi.fn(), // only mock the external call
  };
});
```

---

## Type-Safe Mocks

```typescript
import type { Database } from "@/lib/db";

// Create a typed mock
const mockDb: vi.Mocked<Database> = {
  query: vi.fn(),
  transaction: vi.fn(),
  close: vi.fn(),
};

// TypeScript enforces correct mock shape — can't accidentally miss methods
```

### Mock Return Types Match Real Types

```typescript
// WRONG — returns a string where the real function returns a User object
vi.mocked(getUser).mockResolvedValue("alice" as any);

// RIGHT — returns the correct type
vi.mocked(getUser).mockResolvedValue({
  id: 1,
  name: "Alice",
  email: "a@b.com",
  createdAt: new Date(),
});
```

---

## Testing React Components

### Test Behavior, Not Implementation

```tsx
// WRONG — tests internal state
test("sets loading state", () => {
  const { result } = renderHook(() => useAuth());
  expect(result.current.isLoading).toBe(true);
});

// RIGHT — tests what the user sees
test("shows loading spinner while authenticating", () => {
  render(<LoginForm />);
  expect(screen.getByRole("progressbar")).toBeInTheDocument();
});

test("shows error message on failed login", async () => {
  vi.mocked(login).mockRejectedValue(new Error("Invalid credentials"));
  render(<LoginForm />);
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
  expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
});
```

### Test User Interactions

```tsx
test("submits form with user input", async () => {
  const onSubmit = vi.fn();
  render(<ContactForm onSubmit={onSubmit} />);

  await userEvent.type(screen.getByLabelText(/name/i), "Alice");
  await userEvent.type(screen.getByLabelText(/email/i), "a@b.com");
  await userEvent.click(screen.getByRole("button", { name: /submit/i }));

  expect(onSubmit).toHaveBeenCalledWith({
    name: "Alice",
    email: "a@b.com",
  });
});
```

---

## Testing API Routes

### Next.js App Router Route Handlers

```typescript
import { GET, POST } from "@/app/api/users/route";
import { NextRequest } from "next/server";

test("GET /api/users returns user list", async () => {
  vi.mocked(db.query).mockResolvedValue([
    { id: 1, name: "Alice" },
  ]);

  const req = new NextRequest("http://localhost/api/users");
  const res = await GET(req);
  const data = await res.json();

  expect(res.status).toBe(200);
  expect(data.users).toHaveLength(1);
  expect(data.users[0].name).toBe("Alice");
});

test("POST /api/users validates input", async () => {
  const req = new NextRequest("http://localhost/api/users", {
    method: "POST",
    body: JSON.stringify({ name: "" }), // invalid
  });
  const res = await POST(req);
  expect(res.status).toBe(422);
});
```

---

## Async Patterns

### Test Promises Properly

```typescript
// WRONG — doesn't await, test passes before assertion runs
test("fetches data", () => {
  fetchData().then((data) => {
    expect(data).toBeDefined(); // never runs if promise rejects
  });
});

// RIGHT
test("fetches data", async () => {
  const data = await fetchData();
  expect(data).toBeDefined();
});

// Test rejection
test("throws on invalid input", async () => {
  await expect(fetchData(-1)).rejects.toThrow("Invalid ID");
});
```

### Test Timers

```typescript
test("debounces search input", async () => {
  vi.useFakeTimers();
  const onSearch = vi.fn();
  render(<SearchInput onSearch={onSearch} debounceMs={300} />);

  await userEvent.type(screen.getByRole("searchbox"), "hello");

  // Not called yet — debounce active
  expect(onSearch).not.toHaveBeenCalled();

  vi.advanceTimersByTime(300);

  expect(onSearch).toHaveBeenCalledWith("hello");
  vi.useRealTimers();
});
```

---

## Cleanup and Isolation

### Reset Mocks Between Tests

```typescript
afterEach(() => {
  vi.restoreAllMocks(); // restores original implementations
});

// Or per-file:
beforeEach(() => {
  vi.clearAllMocks(); // clears call history but keeps mock implementations
});
```

### Avoid Module-Level Side Effects

```typescript
// WRONG — shared state across tests
let cache = new Map();

// RIGHT — fresh per test
let cache: Map<string, string>;
beforeEach(() => {
  cache = new Map();
});
```
