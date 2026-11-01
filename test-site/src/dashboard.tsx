import { useEffect, useState } from "react";
import { api, type Candidate, type Interview } from "./api";
import { useAuth } from "./auth";
import { Link } from "./router";
import { Avatar, formatDate, fullName, Icon, StageBadge } from "./ui";

export function DashboardPage() {
  const { user } = useAuth();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [interviews, setInterviews] = useState<Interview[]>([]);
  const [stages, setStages] = useState<string[]>([]);
  useEffect(() => {
    api.candidates().then(setCandidates);
    api.interviews().then(setInterviews);
    api.meta().then((m) => setStages(m.stages));
  }, []);

  const count = (stage: string) => candidates.filter((c) => c.stage === stage).length;
  const max = Math.max(1, ...stages.map(count));
  const stats = [
    { label: "Active candidates", value: candidates.length, trend: "+12% this month", icon: "users" },
    { label: "In interview", value: count("Interview"), trend: "4 this week", icon: "calendar" },
    { label: "Offers out", value: count("Offer"), trend: "2 awaiting reply", icon: "sparkle" },
    { label: "Open roles", value: 5, trend: "1 closing soon", icon: "briefcase" },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Good morning, {user?.name.split(" ")[0]}</h1>
          <p className="muted">Here is what is happening in your pipeline today.</p>
        </div>
        <Link to="/candidates/new" className="button primary"><Icon name="plus" size={16} />New candidate</Link>
      </div>
      <div className="stats">
        {stats.map((s) => (
          <div key={s.label} className="card stat">
            <div className="stat-icon"><Icon name={s.icon} /></div>
            <span className="muted">{s.label}</span>
            <strong>{s.value}</strong>
            <span className="trend">{s.trend}</span>
          </div>
        ))}
      </div>
      <div className="grid-2">
        <section className="card">
          <h2>Pipeline</h2>
          <div className="pipeline">
            {stages.map((s) => (
              <div key={s} className="pipeline-row">
                <span>{s}</span>
                <div className="bar"><div className={`bar-fill stage-${s.toLowerCase()}`} style={{ width: `${(count(s) / max) * 100}%` }} /></div>
                <strong>{count(s)}</strong>
              </div>
            ))}
          </div>
        </section>
        <section className="card">
          <h2>Upcoming interviews</h2>
          {interviews.length === 0 ? (
            <p className="muted empty-small">No interviews scheduled yet. Schedule one from a candidate's menu.</p>
          ) : (
            <ul className="list">
              {interviews.slice(0, 5).map((iv) => (
                <li key={iv.id}>
                  <Avatar name={iv.candidate} />
                  <div>
                    <strong>{iv.candidate}</strong>
                    <span className="muted">{iv.type} with {iv.interviewer}</span>
                  </div>
                  <span className="pill"><Icon name="clock" size={14} />{formatDate(iv.date)} · {iv.time}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <section className="card">
        <h2>Recently applied</h2>
        <ul className="list">
          {candidates.slice(0, 5).map((c) => (
            <li key={c.id}>
              <Avatar name={fullName(c)} />
              <div>
                <strong>{fullName(c)}</strong>
                <span className="muted">{c.job} · applied {formatDate(c.appliedOn)}</span>
              </div>
              <StageBadge stage={c.stage} />
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
