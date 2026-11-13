import { countdownParts } from "@/format";

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * Departure-board countdown. Each digit is its own tile and is keyed by its value, so a
 * tile re-mounts (and flips in) only when its digit changes.
 */
export function SplitFlap({ seconds }: { seconds: number }) {
  const { days, hours, minutes, seconds: secs } = countdownParts(seconds);
  const groups = [
    ...(days > 0 ? [{ label: days === 1 ? "day" : "days", value: String(days) }] : []),
    { label: "hours", value: pad(hours) },
    { label: "min", value: pad(minutes) },
    { label: "sec", value: pad(secs) },
  ];
  return (
    <div className="flex items-start gap-2 sm:gap-3" role="timer" aria-label={`${days} days ${hours} hours ${minutes} minutes ${secs} seconds`}>
      {groups.map((group, g) => (
        <div key={group.label} className="flex items-start gap-2 sm:gap-3">
          {g > 0 && <span className="font-poster pt-1 text-4xl text-white/40 sm:text-5xl">:</span>}
          <div className="flex flex-col items-center gap-1.5">
            <div className="font-poster flex gap-1 text-5xl [perspective:400px] sm:text-6xl" aria-hidden>
              {group.value.split("").map((digit, i) => (
                <span key={`${i}-${digit}`} className="flap tabular">
                  {digit}
                </span>
              ))}
            </div>
            <span className="text-xs text-white/60">{group.label}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
