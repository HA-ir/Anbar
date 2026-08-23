# Contributing to anbar

Thanks for your interest in improving anbar! 🎉

## Project layout

```
src/anbar/        application code (FastAPI)
  api/            HTTP layer (upload, download, admin, web UI routes)
  storage/        Telegram bot + MTProto backends behind one interface
  ui/             single-file SPA (vanilla JS, fa/en i18n)
tests/            pytest suite (162 tests, all must stay green)
docs/             ARCHITECTURE / API / DEPLOY / ROADMAP
docker/           Dockerfile + example compose file
```

## Development setup

```bash
git clone https://github.com/HA-ir/Anbar.git
cd anbar
uv sync --extra dev          # or: pip install -e '.[dev]'
cp docker/compose.yaml docker/compose.local.yaml   # tweak as needed
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

A `fake` backend exists for tests/dev so you never need a real Telegram bot:

```bash
ANBAR_BACKEND=fake ANBAR_AUTH_ENABLED=false \
  uv run uvicorn anbar.main:create_app --factory --port 8567
curl http://127.0.0.1:8567/healthz
```

## Ground rules

1. **One feature per branch**, small commits (`feat: …`, `fix: …`, `docs: …`).
2. **Tests green + ruff clean** before every push — CI enforces both.
3. New endpoints need: auth-matrix entry in `docs/API.md`, at least one
   golden test, and i18n keys if the UI touches them.
4. Keep the repo **generic**: no hostnames, ports, tokens or personal details
   from any specific deployment. Configure via env, document via examples.
5. Bump the version in **both** `pyproject.toml` and `src/anbar/__init__.py`
   if you touch runtime behavior.

## Pull requests

- Fill in the PR template (or: what/why/how-tested).
- Keep diffs reviewable; split unrelated refactors out.
- CI must pass; maintainers will review as soon as possible.

## Reporting bugs

Open a GitHub issue with: version, backend (`bot`/`mtproto`), minimal repro,
and logs (secrets redacted!). Security issues go through
[SECURITY.md](SECURITY.md) instead.
