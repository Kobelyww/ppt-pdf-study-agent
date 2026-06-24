import { type FormEvent, useState } from "react";

interface LoginPageProps {
  error: string | null;
  isLoading: boolean;
  onLogin: (email: string, password: string) => Promise<void>;
}

function LoginPage({ error, isLoading, onLogin }: LoginPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onLogin(email, password);
  }

  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="login-title">
        <p className="eyebrow">Product Workspace</p>
        <h1 id="login-title">PPT PDF Study Agent</h1>
        <form className="login-form" onSubmit={handleSubmit}>
          <label htmlFor="email">
            <span>Email</span>
            <input
              id="email"
              autoComplete="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label htmlFor="password">
            <span>Password</span>
            <input
              id="password"
              autoComplete="current-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error ? <div className="error-banner compact" role="alert">{error}</div> : null}
          <button className="primary-action" type="submit" disabled={isLoading}>
            {isLoading ? "Signing in" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}

export default LoginPage;
