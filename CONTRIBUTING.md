# Contributing to `maintnote`

Thank you for your interest in contributing to `maintnote`!

## Development Environment

`maintnote` targets **Python 3.10+** and has zero runtime dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,docs]"
```

## Pull Request Workflow

All changes to `main` must go through a Pull Request:

1. Create a descriptive branch from an up-to-date `main` (e.g. `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, or `chore/<topic>`).
2. Commit your changes to that branch and verify all quality gates pass.
3. Push the branch and open a Pull Request against `main`.
4. Ensure all CI checks (`lint-and-typecheck`, `test`, and `docs`) pass before merging.

## Quality Gates

Before opening a pull request, please ensure all checks pass:

```bash
# Run tests with coverage
pytest --cov=maintnote --cov-report=term-missing

# Lint & formatting
ruff check src tests
ruff format --check src tests

# Strict type checking
mypy src tests
```

Or run everything at once via Make:

```bash
make check
```

## Coding Guidelines

- Keep runtime dependencies at zero (Python standard library only).
- Maintain `mypy --strict` compliance across all `src/` and `tests/` modules.
- Preserve RFC 5545 compliance and cite relevant sections of
  `draft-gunter-calext-maintenance-notifications-00` in docstrings and tests when changing
  specification behavior.
- Add unit tests for every new feature, workflow transition, or bug fix.

## License

By contributing to `maintnote`, you agree that your contributions will be licensed under
the GNU General Public License v3.0 or later (`GPL-3.0-or-later`).
