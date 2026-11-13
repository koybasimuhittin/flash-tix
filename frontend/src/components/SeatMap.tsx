import { memo } from "react";
import { formatPrice } from "@/format";
import { seatId } from "@/seats";
import type { SeatState } from "@/seats";
import type { Section } from "@/types";

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
    <div className="overflow-x-auto">
      <div className="mx-auto w-fit min-w-full">
        <Stage />
        <div className="flex flex-col gap-7">
          {ordered.map((section) => (
            <div key={section.code} className="flex flex-col items-center gap-2">
              <div className="flex items-baseline gap-2 text-sm">
                <span className="inline-flex size-6 items-center justify-center rounded bg-ink text-xs font-bold text-white">
                  {section.code}
                </span>
                <span className="font-semibold">{section.name}</span>
                <span className="tabular text-muted-foreground">{formatPrice(section.price_cents)}</span>
              </div>
              <div className="flex flex-col gap-1">
                {Array.from({ length: section.rows }, (_, r) => {
                  const row = r + 1;
                  return (
                    <div key={row} className="flex items-center gap-1">
                      <span className="tabular w-6 pr-1 text-right text-[11px] text-muted-foreground">{row}</span>
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
                      <span className="w-6" />
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default memo(SeatMap);

/** The stage as a shallow arc above the seats. */
function Stage() {
  return (
    <div className="mx-auto mb-8 w-full max-w-md">
      <svg viewBox="0 0 400 48" className="w-full" aria-hidden>
        <path d="M8 40 Q200 -8 392 40 Z" fill="var(--ink)" />
      </svg>
      <p className="-mt-1 text-center text-xs font-medium text-muted-foreground">Stage</p>
    </div>
  );
}

export function SeatLegend() {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {(Object.keys(LABELS) as SeatState[]).map((state) => (
        <li key={state} className="flex items-center gap-1.5">
          <span className={`seat seat-${state} !animate-none`} /> {LABELS[state]}
        </li>
      ))}
    </ul>
  );
}
