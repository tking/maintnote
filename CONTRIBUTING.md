# Contributing to `maintnote`

Follow these rules when you contribute to `maintnote`.

## Development Environment

`maintnote` supports Python **3.10 and newer** and has zero runtime dependencies.

Create a virtual environment and install all development and documentation tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,docs]"
```

## Pull Request Workflow

Submit all changes to `main` through a Pull Request:

1. Create a descriptive branch from an up-to-date `main` branch (for example, `feat/topic`, `fix/topic`, `docs/topic`, or `chore/topic`).
2. Commit your changes to that branch and run all quality checks.
3. Push the branch and open a Pull Request against `main`.
4. Make sure all CI checks (`lint-and-typecheck`, `test`, and `docs`) pass before merge.

## Quality Checks

Run these checks before you open a Pull Request:

```bash
# Run tests with coverage
pytest --cov=maintnote --cov-report=term-missing

# Check lint rules and formatting
ruff check src tests
ruff format --check src tests

# Run strict type checks
mypy src tests

# Build documentation in strict mode
mkdocs build --strict
```

To run lint, type checks, and tests with Make, run:

```bash
make check
```

## Coding Rules

- Keep runtime dependencies at zero (use only the Python standard library).
- Make sure `mypy --strict` passes for all modules in `src/` and `tests/`.
- Follow RFC 5545. When you change specification behavior, cite the relevant section of `draft-gunter-calext-maintenance-notifications-00` in docstrings and tests.
- Add unit tests for every new feature, workflow transition, or bug fix.

## License

When you contribute to `maintnote`, you agree to license your contributions under the GNU General Public License v3.0 or later (`GPL-3.0-or-later`).
