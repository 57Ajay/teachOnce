export type Candidate = {
  id: number; firstName: string; lastName: string; email: string; phone: string;
  job: string; stage: string; source: string; appliedOn: string; interviews?: Interview[];
};
export type Interview = {
  id: string; candidateId: number; candidate: string; type: string; date: string; time: string;
  duration: string; interviewer: string; invite: boolean; notes: string;
};
export type Meta = { jobs: string[]; stages: string[]; sources: string[]; interviewers: string[] };

export class ApiError extends Error {
  constructor(message: string, public field?: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  const body = await res.json();
  if (!res.ok) throw new ApiError(body.error ?? "Something went wrong", body.field);
  return body as T;
}

const post = <T>(path: string, body: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  meta: () => call<Meta>("/meta"),
  login: (email: string, password: string) => post<{ name: string; email: string }>("/login", { email, password }),
  candidates: () => call<Candidate[]>("/candidates"),
  candidate: (id: number) => call<Candidate>(`/candidates/${id}`),
  addCandidate: (c: Partial<Candidate>) => post<Candidate>("/candidates", c),
  removeCandidate: (id: number) => call<{ ok: true }>(`/candidates/${id}`, { method: "DELETE" }),
  interviews: () => call<Interview[]>("/interviews"),
  interview: (id: string) => call<Interview>(`/interviews/${id}`),
  schedule: (iv: Partial<Interview>) => post<Interview>("/interviews", iv),
  reset: () => post<{ ok: true; candidates: number }>("/reset", {}),
};
