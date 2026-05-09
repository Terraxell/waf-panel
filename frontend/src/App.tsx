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
 * If the cookie is valid, we also rotate a fresh CSRF token via
 * /auth/csrf so the in-memory store is populated before the user
 * triggers any mutating request.
 */
function useBootstrapSession(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await api.me();
        if (cancelled) return;
        // refreshCsrf already updates the in-memory token store; we
        // just need to mirror the "session is good" flag for RequireAuth.
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
  