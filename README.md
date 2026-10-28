# Teach-Once

**Teach a web task once. Run it a thousand times. Let it heal itself when the site changes.**

Browser agents that ask an LLM what to do on every click are slow, expensive and flaky at volume.
Teach-Once flips that:

1. **Teach**: do the task once in your browser while narrating it.
2. **Compile**: Meta's models turn the recording into a deterministic, parameterized workflow.
3. **Run**: the workflow runs over a CSV batch with zero model calls on the happy path.
4. **Heal**: when the site changes and a step breaks, Muse Spark works out what the step meant,
   SAM 3.1 finds that element on the new screen, and the workflow is patched, verified and versioned.

Built for the Meta Global AI Developer Hackathon. Work in progress.

## Quick start

Requires [uv](https://docs.astral.sh/uv/), `ffmpeg` and Chrome/Chromium.

```bash
cp .env.example .env   # add your META_API_KEY
uv sync
uv run check_api.py   # one cheap call per Meta model
uv run playwright install chromium
uv run gen_data.py    # 50 fake rows -> data/rows.csv
uv run uvicorn app:app --port 8000
```

Then open http://localhost:8000/portal/login (demo login `operator` / `demo123`).
Add `?drift=1`, `2` or `3` to any portal URL to see the site "redesigned".

To teach a task, open http://localhost:8000/app/teach/new in Chrome, click **Start teaching**, share this tab and the microphone, do the task in the portal while narrating, then click **Stop**.

On the recording page, click **Compile workflow**: Voice Transcribe, Muse Spark and Muse Wonder turn the recording into `data/workflows/<id>.v1.json` (and a standalone Playwright script), dry-run it on the portal, and show what they understood.

With the portal running, run a workflow over the 50 rows in another terminal:

```bash
uv run run.py examples/pay-interstate-tax.v1.json data/rows.csv
```

Now redesign the site mid-run (open http://localhost:8000/portal/login?drift=3, or `?drift=1` / `2`) and watch it heal: the first broken row calls Muse Spark and SAM 3.1, the patched workflow is saved as the next version, and every later row runs with zero model calls again.

Developer notes are in [DOCS.md](DOCS.md).

## License

MIT
