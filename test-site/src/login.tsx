import { useId, useState } from "react";
import { api, ApiError } from "./api";
import { useAuth } from "./auth";
import { t } from "./redesign";
import { useRouter } from "./router";
import { Icon } from "./ui";

export function LoginPage() {
  const { signIn } = useAuth();
  const { navigate } = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const emailId = useId();
  const passwordId = useId();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      signIn(await api.login(email, password));
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login-art" aria-hidden="true">
        <div className="login-art-inner">
          <span className="brand-mark big">H</span>
          <h2>Hire the right people, faster.</h2>
          <p>Pipelines, interviews and offers in one calm workspace.</p>
          <div className="login-stats">
            <div><strong>2.4k</strong><span>candidates</span></div>
            <div><strong>38</strong><span>open roles</span></div>
            <div><strong>4.9</strong><span>team rating</span></div>
          </div>
        </div>
      </div>
      <div className="login-panel">
        <form className="login-form" onSubmit={submit} noValidate>
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">H</span>
            <span>Demoland Hire</span>
          </div>
          <h1>{t("Welcome back", "Log in to Demoland Hire")}</h1>
          <p className="muted">{t("Sign in to your recruiting workspace.", "Your hiring, all in one place.")}</p>
          <div className="field">
            <label htmlFor={emailId}>{t("Work email", "Email address")}</label>
            <input id={emailId} type="email" placeholder={t("you@company.com", "name@work.com")} autoComplete="username" value={email}
              onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor={passwordId}>Password</label>
            <input id={passwordId} type="password" placeholder="••••••••" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && <p className="form-error" role="alert"><Icon name="x" size={16} />{error}</p>}
          <button type="submit" className="button primary wide" disabled={busy}>{busy ? t("Signing in…", "Logging in…") : t("Sign in", "Log in")}</button>
          <div className="demo-login">
            <strong>Demo login</strong>
            <code>recruiter@demoland.test</code>
            <code>hire-demo-2026</code>
          </div>
        </form>
      </div>
    </div>
  );
}
