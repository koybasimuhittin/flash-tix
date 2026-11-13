import { describe, expect, it } from "vitest";
import { seatId, seatState, sectionOf, totalPrice } from "./seats";
import type { SeatSets } from "./seats";
import type { Section } from "./types";

function sets(partial: Partial<Record<keyof SeatSets, string[]>>): SeatSets {
  return {
    sold: new Set(partial.sold),
    held: new Set(partial.held),
    mine: new Set(partial.mine),
    selected: new Set(partial.selected),
  };
}

describe("seat ids", () => {
  it("uses {section}-{row}-{seat}", () => {
    expect(seatId("A", 3, 12)).toBe("A-3-12");
    expect(sectionOf("VIP-1-2")).toBe("VIP");
  });
});

describe("seatState", () => {
  it("defaults to available", () => {
    expect(seatState("A-1-1", sets({}))).toBe("available");
  });

  it("shows my selection", () => {
    expect(seatState("A-1-1", sets({ selected: ["A-1-1"] }))).toBe("selected");
  });

  it("shows my hold as mine even though it is also in held", () => {
    expect(seatState("A-1-1", sets({ held: ["A-1-1"], mine: ["A-1-1"] }))).toBe("mine");
  });

  it("shows another user's hold as held, overriding a stale selection", () => {
    expect(seatState("A-1-1", sets({ held: ["A-1-1"], selected: ["A-1-1"] }))).toBe("held");
  });

  it("sold wins over everything", () => {
    const all = ["A-1-1"];
    expect(seatState("A-1-1", sets({ sold: all, held: all, mine: all, selected: all }))).toBe("sold");
  });
});

describe("totalPrice", () => {
  const sections: Section[] = [
    { code: "A", name: "Front", price_cents: 5000, rows: 2, seats_per_row: 2, sort_order: 0 },
    { code: "B", name: "Back", price_cents: 2500, rows: 2, seats_per_row: 2, sort_order: 1 },
  ];

  it("prices each seat by its section", () => {
    expect(totalPrice(["A-1-1", "A-1-2", "B-2-1"], sections)).toBe(12500);
  });

  it("is 0 for no seats", () => {
    expect(totalPrice([], sections)).toBe(0);
  });
});
