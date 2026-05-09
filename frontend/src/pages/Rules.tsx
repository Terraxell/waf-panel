import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { MlThresholdSlider } from "@/components/ui/MlThresholdSlider";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { useT } from "@/lib/i18n";
import type { ApiError, RuleCreate, RuleOut, RuleAction, RuleSource } from "@/lib/types";
import "./Rules.css";

const DEFAULT_BODY = `# CRS-style rule template — adjust the SecRule directive below.
SecRule REQUEST_URI "@contains /admin" \\
    "id:9001,phase:1,deny,status:403,msg:'Custom: admin path blocked'"`;

export function Rules() {
  const t = useT();
  const qc = useQueryClient();
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api.listRules() });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me() });
  const [editorOpen, setEditorOpen] = useState(false);

  return (
    <div className="rules stack">
      <header className="rules__head">
        <span className="mono-label">{t("rules.kicker")}</span>
        <h1>{t("rules.title")}</h1>
        <p className="rules__hint">{t("rules.hint")}</p>
      </header>

      <MlThresholdSlider user={me.data} />

      <div className="row" style={{ justifyContent: "flex-end" }}>
        <Button onClick={() => setEditorOpen(true)}>{t("rules.create_button")}</Button>
      </div>

      {rules.isLoading && <Skeleton lines={3} height="2rem" />}
      {rules.error && <p role="alert" className="rules__error">{t("rules.error")}</p>}

      {rules.data && (
        <table className="rules__table">
          <thead>
            <tr>
              <th>{t("rules.col.key")}</th>
              <th>{t("rules.col.source")}</th>
              <th>{t("rules.col.severity")}</th>
              <th>{t("rules.col.action")}</th>
              <th>{t("rules.col.description")}</th>
              <th>{t("rules.col.status")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rules.data.map((r) => (
              <RuleRow
                key={r.id}
                rule={r}
                onChange={() => qc.invalidateQueries({ queryKey: ["rules"] })}
              />
            ))}
            {rules.data.length === 0 && (
              <tr><td colSpan={7} className="rules__empty">{t("rules.empty")}</td></tr>
            )}
          </tbody>
        </table>
      )}

      {editorOpen && (
        <RuleEditor
          onClose={() => setEditorOpen(false)}
          onCreated={() => {
            setEditorOpen(false);
            qc.invalidateQueries({ queryKey: ["rules"] });
          }}
        />
      )}
    </div>
  );
}

function RuleRow({ rule, onChange }: { rule: RuleOut; onChange: () => void }) {
  const t = useT();
  const del = useMutation({
    mutationFn: () => api.deleteRule(rule.id),
    onSuccess: onChange,
  });

  return (
    <tr>
      <td><code>{rule.rule_key}</code></td>
      <td><span className="mono-label">{rule.source}</span></td>
      <td>{rule.severity}</td>
      <td><span className={`rules__action rules__action--${rule.action}`}>{rule.action}</span></td>
      <td className="rules__desc">{rule.description}</td>
      <td>{rule.enabled ? t("rules.row.enabled") : t("rules.row.disabled")}</td>
      <td>
        <Button variant="ghost" onClick={() => del.mutate()} loading={del.isPending}>
          {t("rules.row.delete")}
        </Button>
      </td>
    </tr>
  );
}

function RuleEditor(props: { onClose: () => void; onCreated: () => void }) {
  const t = useT();
  const [form, setForm] = useState<RuleCreate>({
    rule_key: "custom-001",
    source: "custom",
    severity: 3,
    action: "log",
    description: "",
    body: DEFAULT_BODY,
    enabled: true,
  });
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.createRule(form),
    onSuccess: () => props.onCreated(),
    onError: (err: ApiError) => setError(err.message),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    create.mutate();
  }

  return (
    <div className="rules-modal" onClick={props.onClose}>
      <form className="rules-modal__card" onClick={(e) => e.stopPropagation()} onSubmit={onSubmit}>
        <header>
          <span className="mono-label">{t("rules.editor.kicker")}</span>
          <h2>{t("rules.editor.title")}</h2>
        </header>

        <div className="rules-modal__row">
          <Input
            label={t("rules.editor.key_label")}
            value={form.rule_key}
            onChange={(e) => setForm({ ...form, rule_key: e.target.value })}
            required
          />
          <label className="rules-modal__select">
            <span className="mono-label">SOURCE</span>
            <select value={form.source}
              onChange={(e) => setForm({ ...form, source: e.target.value as RuleSource })}>
              <option value="custom">custom</option>
              <option value="crs">crs</option>
              <option value="ml">ml</option>
            </select>
          </label>
          <label className="rules-modal__select">
            <span className="mono-label">ACTION</span>
            <select value={form.action}
              onChange={(e) => setForm({ ...form, action: e.target.value as RuleAction })}>
              <option value="log">log</option>
              <option value="block">block</option>
              <option value="challenge">challenge</option>
            </select>
          </label>
          <label className="rules-modal__select">
            <span className="mono-label">SEVERITY</span>
            <select value={form.severity}
              onChange={(e) => setForm({ ...form, severity: Number(e.target.value) as 1|2|3|4|5 })}>
              {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>

        <Input
          label={t("rules.editor.description_label")}
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          required
        />

        <label className="rules-modal__editor">
          <span className="mono-label">CRS BODY</span>
          <textarea
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            spellCheck={false}
            rows={10}
            required
          />
        </label>

        <label className="rules-modal__check">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
          />
          <span className="mono-label">{t("rules.editor.enable_now")}</span>
        </label>

        {error && <p role="alert" className="rules__error">{error}</p>}

        <div className="row" style={{ justifyContent: "flex-end" }}>
          <Button type="button" variant="ghost" onClick={props.onClose}>{t("rules.editor.cancel")}</Button>
          <Button type="submit" loading={create.isPending}>{t("rules.editor.save")}</Button>
        </div>
      </form>
    </div>
  );
}
