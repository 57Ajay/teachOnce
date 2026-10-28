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

Requires [uv](https://docs.astral.sh/uv/) and `ffmpeg`.

```bash
cp .env.example .env   # add your META_API_KEY
uv sync
uv run check_api.py   # one cheap call per Meta model
```

Developer notes are in [DOCS.md](DOCS.md).

## License

MIT
