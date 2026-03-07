# Contributing to Sonar

## Before you start
- Check open issues and roadmap first to avoid duplicate work.
- For major changes, open an issue first and align on scope.

## Development setup
```bash
# 1) install dependencies
uv sync --group dev

# 2) copy environment file
cp .env.example .env

# 3) run tests and lint
uv run pytest
uv run ruff check tests
```

## Project commands
```bash
# run full pipeline
uv run main.py https://example.com/article

# resume from snapshot
uv run main.py --resume-from analyze
```

## Pull request checklist
- Keep PR focused on one problem.
- Add or update tests for behavior changes.
- Run `uv run pytest` and `uv run ruff check tests` locally.
- Update docs when CLI, config, or output format changes.
- Do not include secrets, local notes, or generated output.

## Commit style
Use clear, imperative commit messages, for example:
- `feat: add fallback search backend selection`
- `fix: handle missing run snapshot on resume`
- `docs: explain bedrock token setup`
