import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api";
import type { EventDetail, EventIn } from "../types";

interface SectionDraft {
  code: string;
  name: string;
  price: string; // dollars, as typed
  rows: string;
  seats_per_row: string;
}

const CODE_RE = /^[A-Z]{1,3}$/;
/** Catalog's limits (SectionIn / EventIn). */
const MAX_SECTIONS = 26;
const MAX_PRICE_CENTS = 10_000_000;

function emptySection(index: number): SectionDraft {
  return { code: String.fromCharCode(65 + (index % 26)), name: "", price: "50", rows: "5", seats_per_row: "20" };
}

/** `<input type="datetime-local">` gives local time without an offset; the API wants ISO with one. */
function localToIso(value: string): string {
  return new Date(value).toISOString();
}

/** Problems that would make the API reject the event (same rules as catalog's EventIn). */
function validate(form: Omit<EventIn, "sections">, sections: SectionDraft[]): string | null {
  if (!form.starts_at || !form.sales_open_at) return "Set both the start time and the sales opening time.";
  if (Date.parse(form.sales_open_at) > Date.parse(form.starts_at)) return "Sales must open before the event starts.";
  if (sections.length === 0) return "Add at least one section.";
  if (sections.length > MAX_SECTIONS) return `At most ${MAX_SECTIONS} sections.`;
  const codes = new Set<string>();
  for (const s of sections) {
    if (!CODE_RE.test(s.code)) return `Section code "${s.code}" must be 1–3 capital letters.`;
    if (codes.has(s.code)) return `Section code "${s.code}" is used twice.`;
    codes.add(s.code);
    if (!s.name.trim()) return `Section ${s.code} needs a name.`;
    const rows = Number(s.rows);
    const seats = Number(s.seats_per_row);
    if (!Number.isInteger(rows) || rows < 1 || rows > 50) return `Section ${s.code}: rows must be 1–50.`;
    if (!Number.isInteger(seats) || seats < 1 || seats > 60) return `Section ${s.code}: seats per row must be 1–60.`;
    const price = Number(s.price);
    if (s.price.trim() === "" || !(price >= 0) || Math.round(price * 100) > MAX_PRICE_CENTS) {
      return `Section ${s.code}: price must be between 0 and ${MAX_PRICE_CENTS / 100}.`;
    }
  }
  return null;
}

export default function CreateEventPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [venue, setVenue] = useState("");
  const [city, setCity] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [salesOpenAt, setSalesOpenAt] = useState("");
  const [sections, setSections] = useState<SectionDraft[]>([emptySection(0)]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const capacity = sections.reduce((sum, s) => sum + (Number(s.rows) || 0) * (Number(s.seats_per_row) || 0), 0);

  function updateSection(index: number, field: keyof SectionDraft, value: string) {
    setSections((list) =>
      list.map((s, i) => (i === index ? { ...s, [field]: field === "code" ? value.toUpperCase() : value } : s)),
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const base = {
      title,
      description,
      venue,
      city,
      starts_at: startsAt && localToIso(startsAt),
      sales_open_at: salesOpenAt && localToIso(salesOpenAt),
    };
    const problem = validate(base, sections);
    if (problem) {
      setError(problem);
      return;
    }
    const body: EventIn = {
      ...base,
      sections: sections.map((s) => ({
        code: s.code,
        name: s.name.trim(),
        price_cents: Math.round(Number(s.price) * 100),
        rows: Number(s.rows),
        seats_per_row: Number(s.seats_per_row),
      })),
    };
    setBusy(true);
    setError(null);
    try {
      await api.post<EventDetail>("/api/events", body);
      navigate("/organizer");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card create-form" onSubmit={submit}>
      <h1>Create event</h1>
      <div className="fields">
        <label>
          Title
          <input required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Venue
          <input required maxLength={200} value={venue} onChange={(e) => setVenue(e.target.value)} />
        </label>
        <label>
          City
          <input required maxLength={100} value={city} onChange={(e) => setCity(e.target.value)} />
        </label>
        <label>
          Event starts
          <input type="datetime-local" required value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
        </label>
        <label>
          Sales open
          <input
            type="datetime-local"
            required
            value={salesOpenAt}
            onChange={(e) => setSalesOpenAt(e.target.value)}
          />
        </label>
      </div>
      <label>
        Description
        <textarea rows={3} maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>

      <h2>Sections</h2>
      <div className="table-wrap">
        <table className="table sections-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Price ($)</th>
              <th>Rows</th>
              <th>Seats / row</th>
              <th className="num">Seats</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sections.map((s, i) => (
              <tr key={i}>
                <td>
                  <input
                    className="code-input"
                    maxLength={3}
                    value={s.code}
                    onChange={(e) => updateSection(i, "code", e.target.value)}
                  />
                </td>
                <td>
                  <input value={s.name} placeholder="e.g. Floor" onChange={(e) => updateSection(i, "name", e.target.value)} />
                </td>
                <td>
                  <input
                    type="number"
                    min={0}
                    max={MAX_PRICE_CENTS / 100}
                    step="0.01"
                    value={s.price}
                    onChange={(e) => updateSection(i, "price", e.target.value)}
                  />
                </td>
                <td>
                  <input type="number" min={1} max={50} value={s.rows} onChange={(e) => updateSection(i, "rows", e.target.value)} />
                </td>
                <td>
                  <input
                    type="number"
                    min={1}
                    max={60}
                    value={s.seats_per_row}
                    onChange={(e) => updateSection(i, "seats_per_row", e.target.value)}
                  />
                </td>
                <td className="num">{(Number(s.rows) || 0) * (Number(s.seats_per_row) || 0)}</td>
                <td>
                  <button
                    type="button"
                    disabled={sections.length === 1}
                    onClick={() => setSections((list) => list.filter((_, j) => j !== i))}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="inline">
        <button
          type="button"
          disabled={sections.length >= MAX_SECTIONS}
          onClick={() => setSections((list) => [...list, emptySection(list.length)])}
        >
          + Add section
        </button>
        <span className="muted">Total capacity: {capacity} seats</span>
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      <div className="inline">
        <button className="primary" disabled={busy}>
          {busy ? "Creating…" : "Create event"}
        </button>
        <button type="button" onClick={() => navigate("/organizer")}>
          Cancel
        </button>
      </div>
    </form>
  );
}
