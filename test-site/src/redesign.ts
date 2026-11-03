// The redesign switch (POST /api/redesign): read once per page load, like a deploy that new sessions pick up.
export let redesign = false;

export async function loadRedesign() {
  try {
    redesign = (await (await fetch("/api/redesign")).json()).on === true;
  } catch {}
  document.documentElement.classList.toggle("v2", redesign);
}

// The original text, or the redesign's.
export const t = (original: string, redesigned: string) => (redesign ? redesigned : original);
