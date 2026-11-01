import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Router = { path: string; search: URLSearchParams; navigate: (to: string) => void };
const RouterContext = createContext<Router>(null!);

export function RouterProvider({ children }: { children: ReactNode }) {
  const [url, setUrl] = useState(location.pathname + location.search);
  useEffect(() => {
    const onPop = () => setUrl(location.pathname + location.search);
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);
  const navigate = (to: string) => {
    history.pushState(null, "", to);
    setUrl(to);
    scrollTo(0, 0);
  };
  const [path, query = ""] = url.split("?");
  return (
    <RouterContext.Provider value={{ path, search: new URLSearchParams(query), navigate }}>{children}</RouterContext.Provider>
  );
}

export const useRouter = () => useContext(RouterContext);

export function Link({ to, className, children }: { to: string; className?: string; children: ReactNode }) {
  const { navigate } = useRouter();
  return (
    <a
      href={to}
      className={className}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey) return;
        e.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}

export function match(pattern: string, path: string): Record<string, string> | null {
  const names: string[] = [];
  const re = new RegExp("^" + pattern.replace(/:(\w+)/g, (_, n) => (names.push(n), "([^/]+)")) + "/?$");
  const m = path.match(re);
  return m ? Object.fromEntries(names.map((n, i) => [n, decodeURIComponent(m[i + 1])])) : null;
}
