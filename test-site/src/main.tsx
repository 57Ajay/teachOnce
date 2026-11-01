import { useEffect, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { AuthProvider, useAuth } from "./auth";
import { CandidatesPage, NewCandidatePage, ProfilePage } from "./candidates";
import { DashboardPage } from "./dashboard";
import { LoginPage } from "./login";
import { Link, match, RouterProvider, useRouter } from "./router";
import { InterviewPage, InterviewsPage, SchedulePage } from "./schedule";
import { JobsPage, SettingsPage } from "./settings";
import { Avatar, Icon, ToastProvider } from "./ui";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { to: "/candidates", label: "Candidates", icon: "users" },
  { to: "/interviews", label: "Interviews", icon: "calendar" },
  { to: "/jobs", label: "Jobs", icon: "briefcase" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

const ROUTES: [string, (p: Record<string, string>) => ReactNode][] = [
  ["/dashboard", () => <DashboardPage />],
  ["/candidates", () => <CandidatesPage />],
  ["/candidates/new", () => <NewCandidatePage />],
  ["/profile/:id", (p) => <ProfilePage id={Number(p.id)} />],
  ["/schedule/:id", (p) => <SchedulePage candidateId={Number(p.id)} />],
  ["/interviews", () => <InterviewsPage />],
  ["/interviews/:id", (p) => <InterviewPage id={p.id} />],
  ["/jobs", () => <JobsPage />],
  ["/settings", () => <SettingsPage />],
];

function Shell() {
  const { path, navigate } = useRouter();
  const { user, signOut } = useAuth();
  useEffect(() => {
    if (!user && path !== "/login") navigate("/login");
    if (user && (path === "/login" || path === "/")) navigate("/dashboard");
  }, [user, path]);
  if (!user || path === "/login") return <LoginPage />;

  const route = ROUTES.map(([pattern, render]) => [match(pattern, path), render] as const).find(([params]) => params);
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">H</span>
          <span>Demoland Hire</span>
        </div>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to} className={`nav-link${path.startsWith(n.to) ? " active" : ""}`}>
              <Icon name={n.icon} />
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-card">
          <Icon name="sparkle" size={16} />
          <div>
            <strong>Demo workspace</strong>
            <p>Fictional company, fake candidates. Reset any time in Settings.</p>
          </div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-title">Talent workspace</div>
          <div className="topbar-user">
            <Avatar name={user.name} size={30} />
            <div>
              <strong>{user.name}</strong>
              <span>{user.email}</span>
            </div>
            <button type="button" className="icon-button" aria-label="Sign out" onClick={signOut}>
              <Icon name="logout" size={16} />
            </button>
          </div>
        </header>
        <main className="content">{route ? route[1](route[0]!) : <NotFound />}</main>
      </div>
    </div>
  );
}

function NotFound() {
  return (
    <div className="empty">
      <h1>Page not found</h1>
      <Link to="/dashboard" className="button">Back to dashboard</Link>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <RouterProvider>
    <AuthProvider>
      <ToastProvider>
        <Shell />
      </ToastProvider>
    </AuthProvider>
  </RouterProvider>,
);
