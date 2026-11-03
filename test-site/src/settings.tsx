import { useEffect, useState } from "react";
import { api, type Candidate } from "./api";
import { redesign } from "./redesign";
import { Icon, useToast } from "./ui";

const LOCATIONS = ["Remote · EU", "Berlin", "Remote · US", "Lisbon", "Remote · APAC"];

export function JobsPage() {
  const [jobs, setJobs] = useState<string[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  useEffect(() => {
    api.meta().then((m) => setJobs(m.jobs));
    api.candidates().then(setCandidates);
  }, []);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Jobs</h1>
          <p className="muted">{jobs.length} open roles</p>
        </div>
      </div>
      <div className="jobs">
        {jobs.map((j, i) => (
          <div key={j} className="card job">
            <div className="stat-icon"><Icon name="briefcase" /></div>
            <h2>{j}</h2>
            <p className="muted">{LOCATIONS[i % LOCATIONS.length]} · Full-time</p>
            <div className="job-foot">
              <span className="pill">{candidates.filter((c) => c.job === j).length} candidates</span>
              <span className="badge stage-applied">Open</span>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export function SettingsPage() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function reset() {
    setBusy(true);
    const r = await api.reset();
    setBusy(false);
    if (redesign) location.reload(); // the reset also switches the redesign off
    else toast(`Demo data reset: ${r.candidates} candidates, no interviews`);
  }
  async function switchDesign(on: boolean) {
    await api.setRedesign(on);
    location.reload();
  }
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Workspace preferences.</p>
        </div>
      </div>
      <section className="card">
        <h2>Workspace</h2>
        <table className="details">
          <tbody>
            <tr><th>Company</th><td>Demoland Staffing (fictional)</td></tr>
            <tr><th>Time zone</th><td>UTC</td></tr>
            <tr><th>Data</th><td>Fake candidates, kept in memory; restarting the server also resets it.</td></tr>
          </tbody>
        </table>
      </section>
      <section className="card">
        <h2>Redesign (demo)</h2>
        <p className="muted">
          Ship a redesign to see how automations cope: a new look, a cookie banner, a renamed menu, reworded labels and
          buttons, and new controls. Resetting the demo data switches it off.
        </p>
        <label className="switch-row">
          <input type="checkbox" role="switch" className="sr-only" checked={redesign}
            onChange={(e) => switchDesign(e.target.checked)} />
          <span className="switch" aria-hidden="true" />
          <span>New design</span>
        </label>
      </section>
      <section className="card danger-zone">
        <h2>Reset demo data</h2>
        <p className="muted">Puts back the original 16 candidates and deletes every interview.</p>
        <button type="button" className="button danger" disabled={busy} onClick={reset}>
          <Icon name="refresh" size={16} />{busy ? "Resetting…" : "Reset demo data"}
        </button>
      </section>
    </>
  );
}
