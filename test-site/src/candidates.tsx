import { useEffect, useId, useState } from "react";
import { api, ApiError, type Candidate, type Meta } from "./api";
import { Link, useRouter } from "./router";
import { Avatar, Dialog, Field, formatDate, fullName, Icon, Menu, StageBadge, useToast } from "./ui";

function useRemove() {
  const { navigate } = useRouter();
  const toast = useToast();
  const [target, setTarget] = useState<Candidate | null>(null);
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    if (!target) return;
    setBusy(true);
    try {
      await api.removeCandidate(target.id);
      setTarget(null);
      navigate(`/candidates?removed=${encodeURIComponent(fullName(target))}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not remove", "error");
    } finally {
      setBusy(false);
    }
  };
  const dialog = target && (
    <Dialog title={`Remove ${fullName(target)}?`} onClose={() => setTarget(null)}>
      <p className="muted">
        Their application for {target.job} and any scheduled interviews will be deleted. This can't be undone.
      </p>
      <div className="dialog-actions">
        <button type="button" className="button" onClick={() => setTarget(null)}>Cancel</button>
        <button type="button" className="button danger" disabled={busy} onClick={confirm}>Yes, remove</button>
      </div>
    </Dialog>
  );
  return { ask: setTarget, dialog };
}

export function CandidatesPage() {
  const { search, navigate } = useRouter();
  const removed = search.get("removed");
  const [all, setAll] = useState<Candidate[] | null>(null);
  const [stages, setStages] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("All");
  const remove = useRemove();
  useEffect(() => void api.candidates().then(setAll), [removed]);
  useEffect(() => void api.meta().then((m) => setStages(m.stages)), []);

  const q = query.trim().toLowerCase();
  const rows = (all ?? []).filter(
    (c) => (stage === "All" || c.stage === stage) &&
      (!q || `${fullName(c)} ${c.email} ${c.job}`.toLowerCase().includes(q)),
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Candidates</h1>
          <p className="muted">{all ? `${all.length} people in your pipeline` : "Loading…"}</p>
        </div>
        <Link to="/candidates/new" className="button primary"><Icon name="plus" size={16} />Add candidate</Link>
      </div>
      {removed && (
        <div className="banner" role="status">
          <Icon name="check" size={16} />
          <span><strong>{removed}</strong> was removed from the pipeline.</span>
          <button type="button" className="icon-button" aria-label="Dismiss" onClick={() => navigate("/candidates")}>
            <Icon name="x" size={16} />
          </button>
        </div>
      )}
      <div className="card table-card">
        <div className="toolbar">
          <div className="search">
            <Icon name="search" size={16} />
            <input type="search" aria-label="Search candidates" placeholder="Search by name, email or role"
              value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="chips" role="group" aria-label="Filter by stage">
            {["All", ...stages].map((s) => (
              <button key={s} type="button" className={`chip${s === stage ? " active" : ""}`} aria-pressed={s === stage}
                onClick={() => setStage(s)}>{s}</button>
            ))}
          </div>
        </div>
        <table className="table">
          <thead>
            <tr><th>Candidate</th><th>Role</th><th>Stage</th><th>Applied</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td>
                  <div className="person">
                    <Avatar name={fullName(c)} />
                    <div>
                      <Link to={`/profile/${c.id}`} className="person-name">{fullName(c)}</Link>
                      <span className="muted">{c.email}</span>
                    </div>
                  </div>
                </td>
                <td>{c.job}</td>
                <td><StageBadge stage={c.stage} /></td>
                <td className="muted">{formatDate(c.appliedOn)}</td>
                <td className="cell-actions">
                  <Menu label="Actions" items={[
                    { label: "View profile", icon: "eye", onSelect: () => navigate(`/profile/${c.id}`) },
                    { label: "Schedule interview", icon: "calendar", onSelect: () => navigate(`/schedule/${c.id}`) },
                    { label: "Remove candidate", icon: "trash", danger: true, onSelect: () => remove.ask(c) },
                  ]} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {all && rows.length === 0 && <p className="muted empty-small">No candidates match “{query}”.</p>}
      </div>
      {remove.dialog}
    </>
  );
}

export function NewCandidatePage() {
  const { navigate } = useRouter();
  const toast = useToast();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [form, setForm] = useState({ firstName: "", lastName: "", email: "", phone: "", job: "", source: "Careers page" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const id = useId();
  useEffect(() => void api.meta().then(setMeta), []);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const missing = Object.fromEntries(
      (["firstName", "lastName", "email", "job"] as const).filter((k) => !form[k].trim()).map((k) => [k, "This field is required"]),
    );
    setErrors(missing);
    if (Object.keys(missing).length) return;
    setBusy(true);
    try {
      const c = await api.addCandidate(form);
      toast(`${fullName(c)} added to ${c.job}`);
      navigate(`/profile/${c.id}`);
    } catch (err) {
      if (err instanceof ApiError) setErrors({ [err.field ?? "form"]: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/candidates" className="back">← Candidates</Link>
          <h1>Add candidate</h1>
          <p className="muted">They'll start in the Applied stage.</p>
        </div>
      </div>
      <form className="card form" onSubmit={submit} noValidate>
        <section>
          <h2>Personal details</h2>
          <div className="form-grid">
            <Field id={`${id}-first`} label="First name" error={errors.firstName}>
              <input id={`${id}-first`} placeholder="Ada" value={form.firstName} onChange={set("firstName")} />
            </Field>
            <Field id={`${id}-last`} label="Last name" error={errors.lastName}>
              <input id={`${id}-last`} placeholder="Lovelace" value={form.lastName} onChange={set("lastName")} />
            </Field>
            <Field id={`${id}-email`} label="Email" error={errors.email}>
              <input id={`${id}-email`} type="email" placeholder="ada@example.com" value={form.email} onChange={set("email")} />
            </Field>
            <Field id={`${id}-phone`} label="Phone" hint="Optional">
              <input id={`${id}-phone`} type="tel" placeholder="+1 555 0100" value={form.phone} onChange={set("phone")} />
            </Field>
          </div>
        </section>
        <section>
          <h2>Application</h2>
          <div className="form-grid">
            <Field id={`${id}-job`} label="Job opening" error={errors.job}>
              <select id={`${id}-job`} value={form.job} onChange={set("job")}>
                <option value="">Choose a role</option>
                {meta?.jobs.map((j) => <option key={j}>{j}</option>)}
              </select>
            </Field>
            <Field id={`${id}-source`} label="Source">
              <select id={`${id}-source`} value={form.source} onChange={set("source")}>
                {meta?.sources.map((s) => <option key={s}>{s}</option>)}
              </select>
            </Field>
          </div>
        </section>
        {errors.form && <p className="form-error" role="alert">{errors.form}</p>}
        <div className="form-actions">
          <Link to="/candidates" className="button">Cancel</Link>
          <button type="submit" className="button primary" disabled={busy}>{busy ? "Saving…" : "Save candidate"}</button>
        </div>
      </form>
    </>
  );
}

export function ProfilePage({ id }: { id: number }) {
  const { navigate } = useRouter();
  const [c, setC] = useState<Candidate | null | undefined>(undefined);
  const [tab, setTab] = useState<"overview" | "interviews">("overview");
  const remove = useRemove();
  useEffect(() => void api.candidate(id).then(setC, () => setC(null)), [id]);
  if (c === undefined) return <p className="muted">Loading…</p>;
  if (c === null) return <div className="empty"><h1>Candidate not found</h1><Link to="/candidates" className="button">Back to candidates</Link></div>;

  const details = [
    ["Email", c.email], ["Phone", c.phone || "—"], ["Job opening", c.job], ["Source", c.source],
    ["Applied", formatDate(c.appliedOn)], ["Stage", c.stage],
  ];
  return (
    <>
      <Link to="/candidates" className="back">← Candidates</Link>
      <div className="card profile-head">
        <Avatar name={fullName(c)} size={64} />
        <div className="profile-title">
          <h1>{fullName(c)}</h1>
          <p className="muted">{c.job} · <StageBadge stage={c.stage} /></p>
          <div className="profile-contact">
            <span><Icon name="mail" size={14} />{c.email}</span>
            {c.phone && <span><Icon name="phone" size={14} />{c.phone}</span>}
          </div>
        </div>
        <div className="profile-actions">
          <button type="button" className="button" onClick={() => remove.ask(c)}><Icon name="trash" size={16} />Remove</button>
          <button type="button" className="button primary" onClick={() => navigate(`/schedule/${c.id}`)}>
            <Icon name="calendar" size={16} />Schedule interview
          </button>
        </div>
      </div>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>Overview</button>
        <button type="button" role="tab" aria-selected={tab === "interviews"} onClick={() => setTab("interviews")}>
          Interviews ({c.interviews?.length ?? 0})
        </button>
      </div>
      {tab === "overview" ? (
        <div className="card">
          <table className="details">
            <tbody>{details.map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="card">
          {c.interviews?.length ? (
            <ul className="list">
              {c.interviews.map((iv) => (
                <li key={iv.id}>
                  <Icon name="calendar" />
                  <div><strong>{iv.type} · {iv.duration}</strong><span className="muted">with {iv.interviewer}</span></div>
                  <Link to={`/interviews/${iv.id}`} className="pill">{formatDate(iv.date)} · {iv.time}</Link>
                </li>
              ))}
            </ul>
          ) : <p className="muted empty-small">No interviews yet.</p>}
        </div>
      )}
      {remove.dialog}
    </>
  );
}
