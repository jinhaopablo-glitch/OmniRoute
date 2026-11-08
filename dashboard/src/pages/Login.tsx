import { useState, type FormEvent } from "react";
import { supabase } from "../lib/supabase";

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setError("Email o contraseña incorrectos.");
  }

  return (
    <div className="login">
      <form className="card stack" onSubmit={submit}>
        <div className="logo">
          <svg width="36" height="36" viewBox="0 0 64 64" aria-hidden="true">
            <rect width="64" height="64" rx="16" fill="#203D2B" />
            <g fill="#F5EBD8">
              <ellipse cx="32" cy="40" rx="11" ry="9" />
              <circle cx="19" cy="27" r="5" />
              <circle cx="27" cy="19" r="5" />
              <circle cx="37" cy="19" r="5" />
              <circle cx="45" cy="27" r="5" />
            </g>
            <circle cx="32" cy="40" r="3" fill="#C66A3D" />
          </svg>
          PUAVI AI
        </div>
        <p className="muted">Entra para ver el trabajo de tus agentes y aprobar sus propuestas.</p>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="password">Contraseña</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && <div className="error">{error}</div>}
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </div>
  );
}
