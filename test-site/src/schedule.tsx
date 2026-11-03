import { useEffect, useId, useState } from "react";
import { api, ApiError, type Candidate, type Interview, type Meta } from "./api";
import { redesign, t } from "./redesign";
import { Link, useRouter } from "./router";
import { Avatar, Field, formatDate, fullName, Icon, Select, useToast } from "./ui";

const TYPES = [
  { value: "Video call", icon: "video" },
  { value: "On-site", icon: "building" },
  { value: "Phone screen", icon: "phone" },
];
const DURATIONS = ["30 min", "45 min", "60 min"];
const TIMES = Array.from({ length: 17 }, (_, i) => `${String(9 + Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
const steps = () => (redesign ? ["When", "Who", "Check"] : ["Details", "Panel", "Review"]);

function RadioCards({ legend, name, options, value, onChange, error, compact }: {
  legend: string; name: string; options: { value: string; icon?: string }[]; value: string;
  onChange: (v: string) => void; error?: string; compact?: boolean;
}) {
  return (
    <fieldset className={`field${error ? " has-error" : ""}`}>
      <legend>{legend}</legend>
      <div className={compact ? "segmented" : "radio-cards"}>
        {options.map((o) => (
          <label key={o.value} className={`${compact ? "segment" : "radio-card"}${o.value === value ? " selected" : ""}`}>
            <input type="radio" className="sr-only" name={name} value={o.value} checked={o.value === value}
              onChange={() => onChange(o.value)} />
            {o.icon && <Icon name={o.icon} size={20} />}
            <span>{o.value}</span>
          </label>
        ))}
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </fieldset>
  );
}

export function SchedulePage({ candidateId }: { candidateId: number }) {
  const { navigate } = useRouter();
  const toast = useToast();
  const id = useId();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ type: "", date: "", time: "", duration: "", interviewer: "", invite: false, notes: "" });
  useEffect(() => {
    api.candidate(candidateId).then(setCandidate);
    api.meta().then(setMeta);
  }, [candidateId]);
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const required = [["type", "date", "time", "duration"], ["interviewer"], []][step] as (keyof typeof form)[];
  function next() {
    const missing = Object.fromEntries(required.filter((k) => !form[k]).map((k) => [k, "Please fill this in"]));
    setErrors(missing);
    if (!Object.keys(missing).length) setStep(step + 1);
  }
  async function confirm() {
    setBusy(true);
    try {
      const iv = await api.schedule({ ...form, candidateId });
      toast(`Interview ${iv.id} scheduled`);
      navigate(`/interviews/${iv.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not schedule", "error");
    } finally {
      setBusy(false);
    }
  }

  if (!candidate || !meta) return <p className="muted">Loading…</p>;
  return (
    <>
      <Link to="/candidates" className="back">← Candidates</Link>
      <div className="page-head">
        <div>
          <h1>Schedule interview</h1>
          <p className="muted person-inline"><Avatar name={fullName(candidate)} size={22} />{fullName(candidate)} · {candidate.job}</p>
        </div>
      </div>
      <ol className="stepper">
        {steps().map((s, i) => (
          <li key={s} className={i < step ? "done" : i === step ? "current" : ""} aria-current={i === step ? "step" : undefined}>
            <span className="step-dot">{i < step ? <Icon name="check" size={14} /> : i + 1}</span>{s}
          </li>
        ))}
      </ol>
      <div className="card form wizard">
        {step === 0 && (
          <>
            <RadioCards legend="Interview type" name="type" options={TYPES} value={form.type}
              onChange={(v) => set("type", v)} error={errors.type} />
            <div className="form-grid">
              <Field id={`${id}-date`} label="Date" error={errors.date}>
                <input id={`${id}-date`} type="date" value={form.date} onChange={(e) => set("date", e.target.value)} />
              </Field>
              <Field id={`${id}-time`} label="Start time" error={errors.time}>
                <select id={`${id}-time`} value={form.time} onChange={(e) => set("time", e.target.value)}>
                  <option value="">Choose a time</option>
                  {TIMES.map((t) => <option key={t}>{t}</option>)}
                </select>
              </Field>
            </div>
            <RadioCards legend="Duration" name="duration" compact options={DURATIONS.map((d) => ({ value: d }))}
              value={form.duration} onChange={(v) => set("duration", v)} error={errors.duration} />
          </>
        )}
        {step === 1 && (
          <>
            {redesign ? (
              <RadioCards legend="Who's interviewing?" name="interviewer" options={meta.interviewers.map((p) => ({ value: p }))}
                value={form.interviewer} onChange={(v) => set("interviewer", v)} error={errors.interviewer} />
            ) : (
              <Select label="Interviewer" placeholder="Select interviewer" options={meta.interviewers} value={form.interviewer}
                onChange={(v) => set("interviewer", v)} error={errors.interviewer} />
            )}
            <label className="switch-row">
              <input type="checkbox" role="switch" className="sr-only" checked={form.invite}
                onChange={(e) => set("invite", e.target.checked)} />
              <span className="switch" aria-hidden="true" />
              <span>{t("Send calendar invite to the candidate", "Email the candidate a calendar invite")}</span>
            </label>
            <Field id={`${id}-notes`} label="Notes for the interviewer" hint="Optional">
              <textarea id={`${id}-notes`} rows={3} placeholder="Focus areas, links, anything useful"
                value={form.notes} onChange={(e) => set("notes", e.target.value)} />
            </Field>
          </>
        )}
        {step === 2 && (
          <table className="details">
            <tbody>
              <tr><th>Candidate</th><td>{fullName(candidate)}</td></tr>
              <tr><th>Type</th><td>{form.type}</td></tr>
              <tr><th>When</th><td>{formatDate(form.date)} at {form.time} · {form.duration}</td></tr>
              <tr><th>Interviewer</th><td>{form.interviewer}</td></tr>
              <tr><th>Calendar invite</th><td>{form.invite ? "Will be sent" : "Not sent"}</td></tr>
            </tbody>
          </table>
        )}
        <div className="form-actions">
          {step > 0 && <button type="button" className="button" onClick={() => setStep(step - 1)}>Back</button>}
          {step < 2 ? (
            <button type="button" className="button primary" onClick={next}>Continue</button>
          ) : (
            <button type="button" className="button primary" disabled={busy} onClick={confirm}>
              {busy ? "Scheduling…" : "Confirm interview"}
            </button>
          )}
        </div>
      </div>
    </>
  );
}

export function InterviewPage({ id }: { id: string }) {
  const [iv, setIv] = useState<Interview | null | undefined>(undefined);
  useEffect(() => void api.interview(id).then(setIv, () => setIv(null)), [id]);
  if (iv === undefined) return <p className="muted">Loading…</p>;
  if (iv === null) return <div className="empty"><h1>Interview not found</h1></div>;
  return (
    <div className="confirm">
      <div className="confirm-icon"><Icon name="check" size={28} /></div>
      <h1>{t("Interview scheduled", "Interview booked")}</h1>
      <p className="muted">{iv.invite ? `A calendar invite is on its way to ${iv.candidate}.` : "No invite was sent."}</p>
      <div className="card">
        <table className="details">
          <tbody>
            <tr><th>{t("Interview ID", "Booking reference")}</th><td><strong>{iv.id}</strong></td></tr>
            <tr><th>Candidate</th><td>{iv.candidate}</td></tr>
            <tr><th>Type</th><td>{iv.type}</td></tr>
            <tr><th>Date</th><td>{formatDate(iv.date)}</td></tr>
            <tr><th>Time</th><td>{iv.time} · {iv.duration}</td></tr>
            <tr><th>Interviewer</th><td>{iv.interviewer}</td></tr>
          </tbody>
        </table>
      </div>
      <div className="form-actions center">
        <Link to={`/profile/${iv.candidateId}`} className="button">View profile</Link>
        <Link to="/candidates" className="button primary">Back to candidates</Link>
      </div>
    </div>
  );
}

export function InterviewsPage() {
  const [interviews, setInterviews] = useState<Interview[] | null>(null);
  useEffect(() => void api.interviews().then(setInterviews), []);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Interviews</h1>
          <p className="muted">Everything on the calendar.</p>
        </div>
      </div>
      <div className="card table-card">
        {interviews?.length ? (
          <table className="table">
            <thead><tr><th>ID</th><th>Candidate</th><th>Type</th><th>When</th><th>Interviewer</th></tr></thead>
            <tbody>
              {interviews.map((iv) => (
                <tr key={iv.id}>
                  <td><Link to={`/interviews/${iv.id}`} className="mono">{iv.id}</Link></td>
                  <td><div className="person"><Avatar name={iv.candidate} size={26} />{iv.candidate}</div></td>
                  <td>{iv.type}</td>
                  <td>{formatDate(iv.date)} · {iv.time} · {iv.duration}</td>
                  <td>{iv.interviewer}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted empty-small">{interviews ? "No interviews yet. Schedule one from the Candidates page." : "Loading…"}</p>}
      </div>
    </>
  );
}
