# Repository Agent Guidelines

## Pull Request Workflow (Mandatory)

All changes to this codebase **must** be submitted as Pull Requests:

1. **Never commit or push directly to `main`.** Always start from an up-to-date `main` branch and create a descriptive working branch (for example, `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, or `chore/<topic>`).
2. **Make and commit all changes on the branch.** Keep commits focused and well-described.
3. **Push the branch and open a Pull Request against `main`** (e.g., using `gh pr create`).
4. **Verify CI passes** (`lint-and-typecheck`, `test` on Python 3.10–3.13, and `docs`). Do not merge the Pull Request unless the user explicitly asks you to merge it.

## Quality Gates

Before opening or updating a Pull Request, ensure all CI checks pass:

- Lint: `ruff check src tests`
- Formatting: `ruff format --check src tests`
- Strict type checking: `mypy src tests` (targeting Python 3.10)
- Tests & coverage: `pytest --cov=maintnote --cov-report=term-missing`
- Documentation: `mkdocs build --strict`

## Project Conventions

- Keep runtime dependencies at zero (Python 3.10+ standard library only).
- Maintain `mypy --strict` compliance across both `src/` and `tests/`.
- Preserve RFC 5545 and `draft-gunter-calext-maintenance-notifications-00` compliance, citing relevant sections in docstrings and tests when changing specification behavior.
- Add unit tests for every new feature, workflow transition, or bug fix.
