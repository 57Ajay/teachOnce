// Demoland Hire: a fictional recruiting app for Teach-Once demos. In-memory data, reset with POST /api/reset.
import index from "./src/index.html";
import seed from "./seed.json";

type Candidate = (typeof seed.candidates)[number];
type Interview = {
  id: string; candidateId: number; candidate: string; type: string; date: string; time: string;
  duration: string; interviewer: string; invite: boolean; notes: string;
};

let candidates: Candidate[] = [];
let interviews: Interview[] = [];
let nextId = 1;
let nextInterview = 1042;

function reset() {
  candidates = structuredClone(seed.candidates);
  interviews = [];
  nextId = Math.max(...candidates.map((c) => c.id)) + 1;
  nextInterview = 1042;
}
reset();

const json = (data: unknown, status = 200) => Response.json(data, { status });
const fail = (status: number, error: string, field?: string) => json({ error, field }, status);
const required = (body: Record<string, unknown>, fields: string[]) =>
  fields.find((f) => !String(body[f] ?? "").trim());

const server = Bun.serve({
  port: Number(process.env.PORT ?? 3000),
  hostname: "127.0.0.1",
  development: process.env.NODE_ENV !== "production",
  routes: {
    "/*": index,
    "/api/meta": () => json({ jobs: seed.jobs, stages: seed.stages, sources: seed.sources, interviewers: seed.interviewers }),
    "/api/login": {
      POST: async (req) => {
        const { email, password } = await req.json();
        if (email !== seed.user.email || password !== seed.user.password) return fail(401, "Wrong email or password");
        return json({ name: seed.user.name, email });
      },
    },
    "/api/reset": { POST: () => (reset(), json({ ok: true, candidates: candidates.length })) },
    "/api/candidates": {
      GET: () => json(candidates),
      POST: async (req) => {
        const body = await req.json();
        const missing = required(body, ["firstName", "lastName", "email", "job"]);
        if (missing) return fail(422, "This field is required", missing);
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email)) return fail(422, "Enter a valid email address", "email");
        if (candidates.some((c) => c.email.toLowerCase() === body.email.toLowerCase()))
          return fail(409, "A candidate with this email already exists", "email");
        const c: Candidate = {
          id: nextId++, firstName: body.firstName.trim(), lastName: body.lastName.trim(), email: body.email.trim(),
          phone: body.phone ?? "", job: body.job, stage: "Applied", source: body.source || "Careers page",
          appliedOn: new Date().toISOString().slice(0, 10),
        };
        candidates.unshift(c);
        return json(c, 201);
      },
    },
    "/api/candidates/:id": {
      GET: (req) => {
        const c = candidates.find((c) => c.id === Number(req.params.id));
        return c ? json({ ...c, interviews: interviews.filter((i) => i.candidateId === c.id) }) : fail(404, "Not found");
      },
      DELETE: (req) => {
        const before = candidates.length;
        candidates = candidates.filter((c) => c.id !== Number(req.params.id));
        return candidates.length < before ? json({ ok: true }) : fail(404, "Not found");
      },
    },
    "/api/interviews": {
      GET: () => json(interviews),
      POST: async (req) => {
        const body = await req.json();
        const c = candidates.find((c) => c.id === Number(body.candidateId));
        if (!c) return fail(404, "Candidate not found");
        const missing = required(body, ["type", "date", "time", "duration", "interviewer"]);
        if (missing) return fail(422, "This field is required", missing);
        const iv: Interview = { ...body, id: `IV-${nextInterview++}`, candidateId: c.id, candidate: `${c.firstName} ${c.lastName}` };
        interviews.unshift(iv);
        c.stage = "Interview";
        return json(iv, 201);
      },
    },
    "/api/interviews/:id": {
      GET: (req) => {
        const iv = interviews.find((i) => i.id === req.params.id);
        return iv ? json(iv) : fail(404, "Not found");
      },
    },
  },
});

console.log(`Demoland Hire on ${server.url} (login ${seed.user.email} / ${seed.user.password})`);
