import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import type { ApiError } from "@/lib/types";
import "./Login.css";

export function Login() {
  const t = useT();
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const token = await api.login(email, password);
      setToken(token.access_token);
      navigate("/", { replace: true });
    } catch (err) {
      const apiErr = err as ApiError;
      // WHY: never echo backend message verbatim for login — keep a stable
      //      single phrase so we don't leak which half of the credentials
      //      failed. 429 is its own case — operator brute-force gating.
      if (apiErr.status === 429) setError(t("login.error_throttled"));
      else if (apiErr.status === 401) setError(t("login.error_bad_creds"));
      else setError(t("login.error_generic"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login">
      <div className="login__card">
        <span className="mono-label">{t("login.kicker")}</span>
        <h1>{t("login.title")}</h1>
        <p className="login__hint">
          {t("login.hint", { email: "admin@example.com", password: "admin" })}
        </p>
        <form className="stack" onSubmit={onSubmit} noValidate>
          <Input
            label={t("login.email_label")}
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <Input
            label={t("login.password_label")}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            error={error ?? undefined}
          />
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <Button type="submit" loading={loading}>{t("login.submit")}</Button>
          </div>
        </form>
      </div>
    </main>
  );
}
