# Sample project: Users API

A tiny, dependency-free users API used as the target codebase for the AI Coding Agent.

- `app/models.py`   request/response models and validation
- `app/services.py` in-memory user store
- `app/main.py`     HTTP-style routing and error mapping
- `tests/`          tests (`pytest -q`, or `python -m unittest discover -s tests -t .`)
