import { createContext, useContext, useState, type ReactNode } from "react";

type User = { name: string; email: string };
type Auth = { user: User | null; signIn: (u: User) => void; signOut: () => void };
const AuthContext = createContext<Auth>(null!);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => JSON.parse(sessionStorage.getItem("hire-user") ?? "null"));
  const signIn = (u: User) => (sessionStorage.setItem("hire-user", JSON.stringify(u)), setUser(u));
  const signOut = () => (sessionStorage.removeItem("hire-user"), setUser(null));
  return <AuthContext.Provider value={{ user, signIn, signOut }}>{children}</AuthContext.Provider>;
}
