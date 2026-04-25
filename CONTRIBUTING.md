# Contributing

Thanks for helping improve VAEN.

## Development Setup

Use Python 3.11 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Run Tests

```bash
python -m pytest
```

## Working on Changes

- Keep changes small and focused.
- Match the existing CLI and documentation style.
- Do not include secrets, `.env` files, private keys, OAuth state, or credential stores in examples or bundles.
- When changing build, import, or doctor behavior, update the relevant docs and examples.
- Prefer clear error messages that explain what the user should fix.

## Pull Requests

Before opening a pull request:

- Run the test suite.
- Check that new documentation examples are copy-pasteable.
- Note any behavior changes in the PR description.
- Include screenshots for website changes when visual layout changes.
