import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, errorMessage } from "../api";
import { useAuth } from "../auth";

/** Only same-site paths are allowed as a redirect target. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "INVALID_CREDENTIALS"
          ? "Wrong email or password."
          : errorMessage(err),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form" onSubmit={submit}>
      <h1>Log in</h1>
      <label>
        Email
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Password
        <input
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {error && <p className="alert alert-error">{error}</p>}
      <button className="primary" disabled={busy}>
        {busy ? "Logging in…" : "Log in"}
      </button>
      <p className="muted">
        No account? <Link to={`/register${params.size ? `?${params}` : ""}`}>Register</Link>
      </p>
    </form>
  );
}
