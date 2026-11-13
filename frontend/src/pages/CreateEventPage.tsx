import { Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "@/api";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { EventDetail, EventIn } from "@/types";

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
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="font-poster text-5xl">Create event</h1>
      <form className="mt-8 flex flex-col gap-8" onSubmit={submit}>
        <section className="rounded-xl border border-border bg-card p-5 sm:p-6">
          <h2 className="font-poster text-2xl">Event details</h2>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Field id="title" label="Title" className="sm:col-span-2">
              <Input id="title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field id="venue" label="Venue">
              <Input id="venue" required maxLength={200} value={venue} onChange={(e) => setVenue(e.target.value)} />
            </Field>
            <Field id="city" label="City">
              <Input id="city" required maxLength={100} value={city} onChange={(e) => setCity(e.target.value)} />
            </Field>
            <Field id="starts" label="Event starts">
              <Input id="starts" type="datetime-local" required value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
            </Field>
            <Field id="sales" label="Sales open" hint="Seats can be bought from this moment on.">
              <Input
                id="sales"
                type="datetime-local"
                required
                value={salesOpenAt}
                onChange={(e) => setSalesOpenAt(e.target.value)}
              />
            </Field>
            <Field id="description" label="Description" className="sm:col-span-2">
              <Textarea
                id="description"
                rows={3}
                maxLength={5000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-5 sm:p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-poster text-2xl">Sections</h2>
            <p className="tabular text-sm text-muted-foreground">
              Total capacity: <span className="font-semibold text-foreground">{capacity} seats</span>
            </p>
          </div>
          <Table className="sections-table mt-4">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Code</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Price ($)</TableHead>
                <TableHead>Rows</TableHead>
                <TableHead>Seats per row</TableHead>
                <TableHead className="text-right">Seats</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sections.map((s, i) => (
                <TableRow key={i} className="hover:bg-transparent">
                  <TableCell className="pl-0">
                    <Input
                      aria-label={`Section ${i + 1} code`}
                      className="w-16 uppercase"
                      maxLength={3}
                      value={s.code}
                      onChange={(e) => updateSection(i, "code", e.target.value)}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      aria-label={`Section ${i + 1} name`}
                      className="min-w-32"
                      value={s.name}
                      placeholder="e.g. Floor"
                      onChange={(e) => updateSection(i, "name", e.target.value)}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      aria-label={`Section ${i + 1} price`}
                      className="w-24"
                      type="number"
                      min={0}
                      max={MAX_PRICE_CENTS / 100}
                      step="0.01"
                      value={s.price}
                      onChange={(e) => updateSection(i, "price", e.target.value)}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      aria-label={`Section ${i + 1} rows`}
                      className="w-20"
                      type="number"
                      min={1}
                      max={50}
                      value={s.rows}
                      onChange={(e) => updateSection(i, "rows", e.target.value)}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      aria-label={`Section ${i + 1} seats per row`}
                      className="w-20"
                      type="number"
                      min={1}
                      max={60}
                      value={s.seats_per_row}
                      onChange={(e) => updateSection(i, "seats_per_row", e.target.value)}
                    />
                  </TableCell>
                  <TableCell className="tabular text-right">
                    {(Number(s.rows) || 0) * (Number(s.seats_per_row) || 0)}
                  </TableCell>
                  <TableCell className="pr-0 text-right">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove section ${s.code || i + 1}`}
                      disabled={sections.length === 1}
                      onClick={() => setSections((list) => list.filter((_, j) => j !== i))}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-4"
            disabled={sections.length >= MAX_SECTIONS}
            onClick={() => setSections((list) => [...list, emptySection(list.length)])}
          >
            <Plus /> Add section
          </Button>
        </section>

        {error && <Alert variant="error">{error}</Alert>}
        <div className="flex gap-2">
          <Button type="submit" size="lg" disabled={busy}>
            {busy && <Loader2 className="animate-spin" />}
            {busy ? "Creating…" : "Create event"}
          </Button>
          <Button type="button" variant="ghost" size="lg" onClick={() => navigate("/organizer")}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}

function Field({
  id,
  label,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`flex flex-col gap-2 ${className ?? ""}`}>
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
