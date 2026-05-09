import { useEffect, useState, type ReactElement } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { Incidents } from "@/pages/Incidents";
import { Rules } from "@/pages/Rules";
import { Audit } from "@/pages/Audit";
import { Button } from "@/components/ui/Button";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { isAuthenticated, setToken, subscribe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import "./App.css";

function useAuthFlag(): boolean {
  const [authed, setAuthed] = useState(isAuthenticated);
  useEffect(() => subscribe(() => setAuthed(isAuthenticated())), []);
  return authed;
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
          </nav>
          <ThemeToggle />
          <LanguageSwitcher />
          <Button
            variant="ghost"
            onClick={() => {
              setToken(null);
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
];

export function App() {
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
