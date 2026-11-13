// Pure seat logic, shared by the event page and the seat map (and unit-tested).
import type { Section } from "./types";

export type SeatState = "available" | "selected" | "mine" | "held" | "sold";

export interface SeatSets {
  sold: Set<string>;
  held: Set<string>; // every unexpired hold, including the caller's
  mine: Set<string>;
  selected: Set<string>;
}

/** Seat id `{section}-{row}-{seat}`, 1-based, e.g. `A-3-12`. */
export function seatId(section: string, row: number, seat: number): string {
  return `${section}-${row}-${seat}`;
}

export function sectionOf(seat: string): string {
  return seat.split("-")[0];
}

/** Color of one seat. Order matters: sold beats a stale hold, and my hold beats "held". */
export function seatState(id: string, sets: SeatSets): SeatState {
  if (sets.sold.has(id)) return "sold";
  if (sets.mine.has(id)) return "mine";
  if (sets.held.has(id)) return "held";
  if (sets.selected.has(id)) return "selected";
  return "available";
}

/** Total in cents for seats, priced by their section. */
export function totalPrice(seats: string[], sections: Section[]): number {
  const prices = new Map(sections.map((s) => [s.code, s.price_cents]));
  return seats.reduce((sum, s) => sum + (prices.get(sectionOf(s)) ?? 0), 0);
}
