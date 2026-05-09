import { useEffect, useState, type ReactElement } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { Incidents } from "@/pages/Incidents";
import { Rules } from "@/pages/Rules";
import { Audit } from "@/pages/Audit";
import { Drift } from "@/pages/Drift";
import { Users } from "@/pages/Users";
import { Button } from "@/components/ui/Button";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { api } from "@/lib/api";
import { isAuthenticated, setAuthed, subscribe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import "./App.css";

function useAuthFlag(): boolean {
  const [authed, setLocalAuthed] = useState(isAuthenticated);
  useEffect(() => subscribe(() => setLocalAuthed(isAuthenticated())), []);
  return authed;
}

/**
 * On first mount, ask the backend whether the session cookie is still
 * good. ADR-0014: the JWT lives in a httpOnly cookie that JS can't read,
 * so we can't just inspect document.cookie — we have to ping /auth/me.
 *
 * If the cookie is valid, refreshCsrf populates the in-memory CSRF
 * token before the user can trigger any mutating request.
 */
function useBootstrapSession(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await api.me();
        if (cancelled) return;
        await api.refreshCsrf();
        if (cancelled) return;
        setAuthed(true);
      } catch {
        // 401 / network error → user simply isn't logged in. RequireAuth
        // will bounce them to /login. Nothing to do here.
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  return ready;
}

function RequireAuth({ children }: { children: ReactElement }) {
  return useAuthFlag() ? children : <Navigate to="/login" replace />;
}

function Shell({ children }: { children: ReactElement }) {
  const navigate = useNavigate();
  const t = useT();
  return (
    <>
      <header className="page" style={{ paddingBottom: 0 }}>
        <div className="row shell-bar">
          <span className="mono-label">waf-panel</span>
          <nav className="shell-nav">
            <NavLink to="/" end className={({ isActive }) => `shell-link${isActive ? " is-active" : ""}`}>
              {t("nav.dashboard")}
            </NavLink>
            <NavLink to="/incidents" className={({ isActive }) => `shell-link${isActive ? " is-active" : ""}`}>
              {t("nav.incidents")}
            </NavLink>
            <NavLink to="/rules" className={({ isActive }) => `shell-link${isActive ? " is-active" : ""}`}>
              {t("nav.rules")}
            </NavLink>
            <NavLink to="/audit" className={({ isActive }) => `shell-link${isActive ? " is-active" : ""}`}>
              {t("nav.audit")}
            </NavLink>
            <NavLink to="/drift" className={({ isActive }) => `shell-link${isActive ? " is-active" : ""}`}>
              {t("nav.drift")}
            </NavLink>
            <NavLink to="/users" className={({ isActive }) => `shell-link${isActive ? " is-active" : ""}`}>
              {t("nav.users")}
            </NavLink>
          </nav>
          <ThemeToggle />
          <LanguageSwitcher />
          <Button
            variant="ghost"
            onClick={async () => {
              // ADR-0014: server-side logout deletes the httpOnly session
              // cookie. api.logout swallows its own errors so navigation
              // always happens.
              await api.logout();
              navigate("/login", { replace: true });
            }}
          >
            {t("nav.logout")}
          </Button>
        </div>
      </header>
      <main className="page">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </>
  );
}

const SHELL_ROUTES: { path: string; element: ReactElement }[] = [
  { path: "/", element: <Dashboard /> },
  { path: "/incidents", element: <Incidents /> },
  { path: "/rules", element: <Rules /> },
  { path: "/audit", element: <Audit /> },
  { path: "/drift", element: <Drift /> },
  { path: "/users", element: <Users /> },
];

export function App() {
  const ready = useBootstrapSession();
  // Until the boot probe finishes, render nothing rather than
  // RequireAuth flashing a redirect to /login when the user is in
  // fact logged in.
  if (!ready) return null;

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        {SHELL_ROUTES.map(({ path, element }) => (
          <Route
            key={path}
            path={path}
            element={
              <RequireAuth>
                <Shell>{element}</Shell>
              </RequireAuth>
            }
          />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
