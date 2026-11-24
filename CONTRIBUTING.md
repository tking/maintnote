# Contributing to `maintnote`

Thank you for your interest in contributing to `maintnote`!

## Development Environment

`maintnote` targets **Python 3.10+** and has zero runtime dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,docs]"
```

## Quality Gates

Before opening a pull request, please ensure all checks pass:

```bash
# Run tests with coverage
pytest --cov=maintnote --cov-report=term-missing

# Lint & formatting
ruff check src tests
ruff format --check src tests

# Strict type checking
mypy src
```

Or run everything at once via Make:

```bash
make check
```

## Coding Guidelines

- Keep runtime dependencies at zero (Python standard library only).
- Maintain `mypy --strict` compliance across all `src/maintnote` modules.
- Preserve RFC 5545 compliance and cite relevant sections of
  `draft-gunter-calext-maintenance-notifications-00` in docstrings and tests when changing
  specification behavior.
- Add unit tests for every new feature, workflow transition, or bug fix.

## License

By contributing to `maintnote`, you agree that your contributions will be licensed under
the GNU General Public License v3.0 or later (`GPL-3.0-or-later`).
