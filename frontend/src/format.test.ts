import { describe, expect, it } from "vitest";
import { clockOffset, countdownParts, formatDuration, toMillis } from "./format";

describe("formatDuration", () => {
  it("shows a fresh 600 s hold as 10:00, also with a fraction of a second extra", () => {
    expect(formatDuration(600)).toBe("10:00");
    expect(formatDuration(600.9)).toBe("10:00");
  });

  it("formats minutes, hours and days", () => {
    expect(formatDuration(65)).toBe("1:05");
    expect(formatDuration(3725)).toBe("1:02:05");
    expect(formatDuration(90_061)).toBe("1d 1h 1m");
  });

  it("never goes negative", () => {
    expect(formatDuration(-5)).toBe("0:00");
  });
});

describe("toMillis", () => {
  it("parses ISO timestamps with Z or an explicit offset", () => {
    expect(toMillis("2026-11-13T18:00:00Z")).toBe(Date.UTC(2026, 10, 13, 18));
    expect(toMillis("2026-11-13T18:00:00.250000+00:00")).toBe(Date.UTC(2026, 10, 13, 18, 0, 0, 250));
  });
});

describe("clockOffset", () => {
  const server = "2026-11-13T18:00:10Z";
  const serverMs = Date.UTC(2026, 10, 13, 18, 0, 10);

  it("measures how far the server clock is ahead, at the round-trip midpoint", () => {
    // The laptop is 10 s behind; the request took 200 ms.
    const sentAt = serverMs - 10_000 - 100;
    expect(clockOffset(server, sentAt, sentAt + 200)).toBe(10_000);
  });

  it("is negative when the local clock runs ahead", () => {
    const sentAt = serverMs + 3_000;
    expect(clockOffset(server, sentAt, sentAt)).toBe(-3_000);
  });
});

describe("countdownParts", () => {
  it("splits seconds into days, hours, minutes and seconds", () => {
    expect(countdownParts(90_061.7)).toEqual({ days: 1, hours: 1, minutes: 1, seconds: 1 });
    expect(countdownParts(-1)).toEqual({ days: 0, hours: 0, minutes: 0, seconds: 0 });
  });
});
