import { memo } from "react";
import type { Section } from "../types";

export type SeatState = "available" | "selected" | "mine" | "held" | "sold";

export function seatId(section: string, row: number, seat: number): string {
  return `${section}-${row}-${seat}`;
}

const LABELS: Record<SeatState, string> = {
  available: "Available",
  selected: "Selected",
  mine: "Held by you",
  held: "Held by others",
  sold: "Sold",
};

interface Props {
  sections: Section[];
  stateOf: (id: string) => SeatState;
  onToggle: (id: string) => void;
  disabled: boolean;
}

/** One grid per section: `rows` rows of `seats_per_row` seats, ids `{section}-{row}-{seat}`. */
function SeatMap({ sections, stateOf, onToggle, disabled }: Props) {
  const ordered = [...sections].sort((a, b) => a.sort_order - b.sort_order);
  return (
    <div className="seatmap">
      <div className="stage">STAGE</div>
      {ordered.map((section) => (
        <div key={section.code} className="section">
          <h3>
            {section.code} · {section.name}
          </h3>
          <div className="rows">
            {Array.from({ length: section.rows }, (_, r) => {
              const row = r + 1;
              return (
                <div key={row} className="row">
                  <span className="row-label">{row}</span>
                  {Array.from({ length: section.seats_per_row }, (_, s) => {
                    const id = seatId(section.code, row, s + 1);
                    const state = stateOf(id);
                    const clickable = !disabled && (state === "available" || state === "selected");
                    return (
                      <button
                        key={id}
                        className={`seat seat-${state}`}
                        title={`${id} · ${LABELS[state]}`}
                        aria-label={`${id} ${LABELS[state]}`}
                        aria-pressed={state === "selected"}
                        disabled={!clickable}
                        onClick={() => onToggle(id)}
                      />
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export default memo(SeatMap);

export function SeatLegend() {
  return (
    <ul className="legend">
      {(Object.keys(LABELS) as SeatState[]).map((state) => (
        <li key={state}>
          <span className={`seat seat-${state}`} /> {LABELS[state]}
        </li>
      ))}
    </ul>
  );
}
