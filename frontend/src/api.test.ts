import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, setToken, setUnauthorizedHandler } from "./api";

function respond(status: number, body: unknown, contentType = "application/json") {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(text, { status, headers: { "Content-Type": contentType } })));
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (err) {
    return err as ApiError;
  }
  throw new Error("expected the request to fail");
}

afterEach(() => {
  vi.unstubAllGlobals();
  setToken(null);
  setUnauthorizedHandler(() => {});
});

describe("api", () => {
  it("returns parsed JSON and sends the bearer token", async () => {
    respond(200, [{ id: 1 }]);
    setToken("tok");
    expect(await api.get("/api/events")).toEqual([{ id: 1 }]);
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("maps a domain error to code and seats", async () => {
    respond(409, { detail: { code: "SEATS_UNAVAILABLE", seats: ["A-1-2"] } });
    const err = await failure(api.post("/api/booking/holds", {}));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("SEATS_UNAVAILABLE");
    expect(err.seats).toEqual(["A-1-2"]);
  });

  it("joins FastAPI validation messages", async () => {
    respond(422, { detail: [{ msg: "field required" }, { msg: "too long" }] });
    const err = await failure(api.post("/api/events", {}));
    expect(err.code).toBeNull();
    expect(err.message).toBe("field required; too long");
  });

  it.each([
    [429, "RATE_LIMITED", /Slow down/],
    [502, "UPSTREAM_UNAVAILABLE", /not reachable/],
    [503, "SERVICE_UNAVAILABLE", /busy or restarting/],
    [504, "UPSTREAM_TIMEOUT", /took too long/],
  ])("maps the gateway's %i %s to a readable message", async (status, code, message) => {
    respond(status, { detail: { code } });
    const err = await failure(api.get("/api/booking/me"));
    expect(err.code).toBe(code);
    expect(errorMessage(err)).toMatch(message);
  });

  it("falls back to a generic message when the body is not JSON", async () => {
    respond(500, "Internal Server Error", "text/plain");
    const err = await failure(api.get("/api/events"));
    expect(err.code).toBeNull();
    expect(errorMessage(err)).toBe("Something went wrong (HTTP 500). Try again.");
  });

  it("logs out on 401 when a token was sent", async () => {
    const logout = vi.fn();
    setUnauthorizedHandler(logout);
    setToken("expired");
    respond(401, { detail: "token expired" });
    await failure(api.get("/api/booking/me"));
    expect(logout).toHaveBeenCalledOnce();
  });

  it("does not log out on a 401 from login itself (no token)", async () => {
    const logout = vi.fn();
    setUnauthorizedHandler(logout);
    respond(401, { detail: { code: "INVALID_CREDENTIALS" } });
    const err = await failure(api.post("/api/auth/login", {}));
    expect(err.code).toBe("INVALID_CREDENTIALS");
    expect(logout).not.toHaveBeenCalled();
  });

  it("reports network failures plainly", () => {
    expect(errorMessage(new TypeError("Failed to fetch"))).toBe("Cannot reach the server.");
  });
});
