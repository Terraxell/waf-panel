import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { ApiError, Role, UserSummary } from "@/lib/types";
import "./Users.css";

const ROLES: Role[] = ["admin", "analyst", "viewer"];

export function Users() {
  const t = useT();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me() });

  const list = useQuery({
    queryKey: ["users"],
    queryFn: () => api.listUsers(),
    refetchInterval: 60_000,
  });

  // Add-user form local state.
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.createUser({ email, role, password }),
    onSuccess: () => {
      setEmail("");
      setPassword("");
      setRole("viewer");
      setFormError(null);
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err) => {
      // React Query types err as Error; our wrapper actually throws an
      // ApiError shape. Two-step cast through unknown to satisfy TS.
      const apiErr = err as unknown as ApiError;
      setFormError(apiErr.message || t("users.error_generic"));
    },
  });

  const patch = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<UserSummary> }) =>
      api.updateUser(id, {
        role: patch.role,
        is_active: patch.is_active,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  function onCreate(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    create.mutate();
  }

  // Admin-only page; show a clear gate while we don't know the role yet
  // and a 403-style stub when the current user is not admin.
  if (me.isLoading) {
    return <Skeleton lines={4} height="2rem" />;
  }
  if (me.data?.role !== "admin") {
    return (
      <div className="users stack">
        <p role="alert" className="users__forbidden">
          {t("users.forbidden")}
        </p>
      </div>
    );
  }

  return (
    <div className="users stack">
      <header>
        <span className="mono-label">{t("users.kicker")}</span>
        <h1>{t("users.title")}</h1>
        <p className="users__hint">{t("users.hint")}</p>
      </header>

      <section className="users__form-card">
        <h2>{t("users.form.title")}</h2>
        <form className="row users__form" onSubmit={onCreate} noValidate>
          <Input
            label={t("users.form.email")}
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <label className="users__role-select">
            <span className="mono-label">{t("users.col.role")}</span>
            <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </label>
          <Input
            label={t("users.form.password")}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            error={formError ?? undefined}
          />
          <Button type="submit" loading={create.isPending}>
            {t("users.form.submit")}
          </Button>
        </form>
      </section>

      {list.isLoading && <Skeleton lines={4} height="2rem" />}
      {list.error && <p role="alert" className="users__error">{t("users.error_load")}</p>}

      {list.data && (
        <table className="users__table">
          <thead>
            <tr>
              <th>{t("users.col.email")}</th>
              <th>{t("users.col.role")}</th>
              <th>{t("users.col.status")}</th>
              <th>{t("users.col.last_login")}</th>
              <th>{t("users.col.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((u) => {
              const isSelf = u.id === me.data?.id;
              return (
                <tr key={u.id} className={u.is_active ? "" : "users__row--disabled"}>
                  <td><code>{u.email}</code></td>
                  <td>
                    <select
                      value={u.role}
                      disabled={isSelf}
                      onChange={(e) =>
                        patch.mutate({ id: u.id, patch: { role: e.target.value as Role } })
                      }
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <span className={`users__status users__status--${u.is_active ? "active" : "disabled"}`}>
                      {u.is_active ? t("users.status.active") : t("users.status.disabled")}
                    </span>
                  </td>
                  <td>
                    {u.last_login_at
                      ? new Date(u.last_login_at).toLocaleString()
                      : "—"}
                  </td>
                  <td>
                    <div className="row" style={{ gap: "0.5rem" }}>
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={isSelf}
                        onClick={() =>
                          patch.mutate({
                            id: u.id,
                            patch: { is_active: !u.is_active },
                          })
                        }
                      >
                        {u.is_active ? t("users.actions.disable") : t("users.actions.enable")}
                      </Button>
                      <Button
                        type="button"
                        variant="danger"
                        disabled={isSelf || !u.is_active}
                        onClick={() => {
                          if (window.confirm(t("users.actions.delete_confirm", { email: u.email }))) {
                            del.mutate(u.id);
                          }
                        }}
                      >
                        {t("users.actions.delete")}
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {list.data.length === 0 && (
              <tr><td colSpan={5} className="users__empty">{t("users.empty")}</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
