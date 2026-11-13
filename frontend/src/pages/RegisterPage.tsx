import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, errorMessage } from "../api";
import { useAuth } from "../auth";
import { safeNext } from "./LoginPage";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register(email, password, name);
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "EMAIL_TAKEN"
          ? "An account with this email already exists."
          : errorMessage(err),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form" onSubmit={submit}>
      <h1>Create an account</h1>
      <label>
        Name
        <input required maxLength={100} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Email
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Password <span className="muted">(at least 8 characters)</span>
        <input
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {error && <p className="alert alert-error">{error}</p>}
      <button className="primary" disabled={busy}>
        {busy ? "Creating account…" : "Register"}
      </button>
      <p className="muted">
        Already registered? <Link to={`/login${params.size ? `?${params}` : ""}`}>Log in</Link>
      </p>
    </form>
  );
}
