async function startRun(workflow, rows, heal, errorEl) {
  const r = await fetch("/app/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ workflow, rows, heal }),
  });
  const body = await r.json();
  if (r.ok) location.href = `/app/runs/${body.run_id}`;
  else errorEl.textContent = body.detail;
}
