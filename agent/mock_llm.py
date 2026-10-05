"""OFFLINE DEMO PROVIDER (scripted, not an LLM).

Lets the whole agent pipeline run without an API key. The real tools (search, read, patch, diff, tests)
are still executed for real; only the *reasoning* is scripted, and it only knows how to implement the
two demo tasks on the bundled sample project: "age cannot be negative" and generic "input validation"
(the example from the assignment brief). Use a real provider for anything else.
"""
from __future__ import annotations

import re

STOP = set("""add the and for that this with write test tests cannot can not should make sure please into from its all
new when use using have has are was which there their them then a an so it to of in on be is as at by or""".split())

MODEL_ANCHOR = '        if "@" not in self.email:\n            raise ValidationError("email must contain \'@\'")\n'
MODEL_NEW = MODEL_ANCHOR + (
    '        if not isinstance(self.age, int) or isinstance(self.age, bool):\n'
    '            raise ValidationError("age must be an integer")\n'
    '        if self.age < 0:\n'
    '            raise ValidationError("age must be zero or greater")\n'
)
TEST_ANCHOR = "    def test_get_unknown_user_returns_404(self):\n"
TEST_NEW = '''    def test_create_user_rejects_negative_age(self):
        response = self.api.handle("POST", "/users", {**VALID, "age": -1})
        self.assertEqual(response.status, 422)
        self.assertIn("age", response.body["error"])

    def test_create_user_accepts_zero_age(self):
        response = self.api.handle("POST", "/users", {**VALID, "age": 0})
        self.assertEqual(response.status, 201)

    def test_create_user_rejects_non_integer_age(self):
        response = self.api.handle("POST", "/users", {**VALID, "age": "5"})
        self.assertEqual(response.status, 422)

''' + TEST_ANCHOR

# Scenario 2: generic "add input validation" (name length + email shape)
INPUT_NEW = MODEL_ANCHOR.replace(
    '            raise ValidationError("email must contain \'@\'")\n',
    '            raise ValidationError("email must contain \'@\'")\n'
    '        local, _, domain = self.email.partition("@")\n'
    '        if not local or "." not in domain:\n'
    '            raise ValidationError("email must have a name and a domain, e.g. user@example.com")\n'
    '        if len(self.name.strip()) > 100:\n'
    '            raise ValidationError("name must be at most 100 characters")\n',
)
INPUT_TEST_NEW = '''    def test_create_user_rejects_email_without_domain(self):
        response = self.api.handle("POST", "/users", {**VALID, "email": "ada@localhost"})
        self.assertEqual(response.status, 422)
        self.assertIn("email", response.body["error"])

    def test_create_user_rejects_overlong_name(self):
        response = self.api.handle("POST", "/users", {**VALID, "name": "x" * 101})
        self.assertEqual(response.status, 422)
        self.assertIn("name", response.body["error"])

''' + TEST_ANCHOR

ROLES = {
    "models": "Defines the request model and its validation rules",
    "main": "Implements the API endpoints and maps validation errors to HTTP responses",
    "services": "Business logic layer that consumes the model",
}


def _is_demo(task: str) -> bool:
    t = task.lower()
    return "age" in re.findall(r"[a-z]+", t) and ("negative" in t or "< 0" in t or "below zero" in t)


def _is_input_validation(task: str) -> bool:
    t = task.lower()
    return not _is_demo(task) and ("validat" in t or "sanitiz" in t)


class MockLLM:
    name = "offline-demo (scripted, no LLM)"

    def complete_json(self, stage: str, system: str, payload: dict) -> dict:
        return getattr(self, f"_{stage}")(payload)

    def _analyze(self, p: dict) -> dict:
        words = [w for w in re.findall(r"[a-z_]+", p["task"].lower()) if w not in STOP and len(w) > 2]
        keywords = list(dict.fromkeys(words))[:4]
        needs_tests = "test" in p["task"].lower()
        return {
            "task_understanding": f"Implement: \"{p['task'].strip()}\" "
            f"Look for code related to {', '.join(keywords)}"
            + (", and add tests covering the new behaviour." if needs_tests else "."),
            "keywords": keywords,
        }

    def _explore(self, p: dict) -> dict:
        obs, kws = p["observations"], p["keywords"]
        searches = [o for o in obs if o["tool"] == "search_code"]
        if len(searches) < min(2, len(kws)):
            kw = kws[len(searches)]
            return {"thought": f"Search for '{kw}'.", "action": "search_code", "args": {"query": kw}}
        score: dict = {}
        for o in searches:
            for path, n in o.get("hit_files", {}).items():
                score[path] = score.get(path, 0) + n
        tests = [f["path"] for f in p["file_tree"] if f["path"].startswith("tests/") and f["path"].endswith(".py")]
        wanted = [x for x in sorted(score, key=score.get, reverse=True) if x.endswith(".py")][:4] + tests[:2]
        read = {o["args"].get("path") for o in obs if o["tool"] == "read_file"}
        for path in dict.fromkeys(wanted):
            if path not in read and not path.endswith("__init__.py"):
                return {"thought": f"Read {path}.", "action": "read_file", "args": {"path": path}}
        return {"thought": "Enough context.", "action": "finish", "args": {}}

    def _select(self, p: dict) -> dict:
        kws = p["keywords"]
        picked = []
        for path, text in p["contents"].items():
            lines = text.splitlines()
            hit = next(((i, l) for k in reversed(kws) for i, l in enumerate(lines, 1) if k in l.lower()), None)
            stem = path.rsplit("/", 1)[-1].removesuffix(".py")
            is_test = path.startswith("tests/")
            if not hit and not is_test:
                continue
            role = "Existing tests that should be extended for this task" if is_test else ROLES.get(stem, "Matches the task keywords")
            evidence = f" Evidence: line {hit[0]}: `{hit[1].strip()[:80]}`." if hit else ""
            picked.append({"path": path, "reason": role + "." + evidence, "_t": is_test, "_n": sum(any(k in l.lower() for k in kws) for l in lines)})
        picked.sort(key=lambda x: (x["_t"], -x["_n"]))
        return {"relevant_files": [{"path": x["path"], "reason": x["reason"]} for x in picked]}

    def _plan(self, p: dict) -> dict:
        paths = [f["path"] for f in p["relevant_files"]]
        model = next((x for x in paths if "models" in x), paths[0])
        api = next((x for x in paths if x.endswith("main.py")), None)
        test = next((x for x in paths if x.startswith("tests/")), None)
        if _is_input_validation(p["task"]):
            steps = [f"Review {model} to see which request fields are already validated.",
                     "Require the email to have a name and a domain, and cap the name at 100 characters.",
                     "Rely on the existing ValidationError -> 422 mapping in the API layer." if api else "Reuse the existing error mapping.",
                     f"Extend {test} with tests for an email without a domain and an over-long name." if test else "Add tests.",
                     "Run the test suite.", "Generate the diff and summarise the change."]
            return {"plan": steps}
        if not _is_demo(p["task"]):
            return {"plan": [f"Review {', '.join(paths)}", "Implement the requested change",
                             "Add or update tests", "Run the test suite", "Generate diff and summary"]}
        steps = [f"Review {model} to see where input fields are validated.",
                 "Reject non-integer and negative `age` values with a ValidationError."]
        if api:
            steps.append(f"Confirm {api} already maps ValidationError to a 422 response (no change expected).")
        if test:
            steps.append(f"Extend {test} with tests: negative age (422), zero age (201), non-integer age (422).")
        steps += ["Run the test suite.", "Generate the diff and summarise the change."]
        return {"plan": steps}

    def _changes(self, p: dict) -> dict:
        if not (_is_demo(p["task"]) or _is_input_validation(p["task"])):
            return {"changes": [], "note": "Offline demo mode only implements its two scripted demo tasks."}
        if p.get("attempt", 0) > 0:
            return {"changes": []}  # the scripted provider cannot repair failures
        if _is_input_validation(p["task"]):
            changes = []
            for path, text in p["files"].items():
                if MODEL_ANCHOR in text and "local, _, domain" not in text:
                    changes.append({"file": path, "description": "Validate email shape and name length.",
                                    "edits": [{"search": MODEL_ANCHOR, "replace": INPUT_NEW}]})
                if TEST_ANCHOR in text and "rejects_overlong_name" not in text:
                    changes.append({"file": path, "description": "Add tests for email without domain and over-long name.",
                                    "edits": [{"search": TEST_ANCHOR, "replace": INPUT_TEST_NEW}]})
            return {"changes": changes}
        changes = []
        for path, text in p["files"].items():
            if MODEL_ANCHOR in text and "self.age < 0" not in text:
                changes.append({"file": path, "description": "Validate that age is an integer and not negative.",
                                "edits": [{"search": MODEL_ANCHOR, "replace": MODEL_NEW}]})
            if TEST_ANCHOR in text and "rejects_negative_age" not in text:
                changes.append({"file": path, "description": "Add tests for negative, zero and non-integer age.",
                                "edits": [{"search": TEST_ANCHOR, "replace": TEST_NEW}]})
        return {"changes": changes}

    def _summary(self, p: dict) -> dict:
        applied = p["changes"]
        if not applied:
            return {"what_changed": "No changes were applied.", "why": "", "tests_added": [],
                    "limitations": ["Offline demo mode only supports its two scripted demo tasks; configure an LLM provider for other tasks."]}
        has_tests = any("tests/" in c["file"] for c in applied)
        if _is_input_validation(p["task"]):
            tests = ["test_create_user_rejects_email_without_domain", "test_create_user_rejects_overlong_name"] if has_tests else []
            return {
                "what_changed": " ".join(f"{c['file']}: {c['description']}" for c in applied),
                "why": "Malformed emails and unbounded names should be rejected at the model boundary. The API layer already turns "
                       "ValidationError into a 422 response, so no routing change is needed.",
                "tests_added": tests,
                "limitations": ["Output came from the scripted offline provider, not an LLM.",
                                "Only email shape and name length were added; the rules are deliberately simple."],
            }
        tests = ["test_create_user_rejects_negative_age", "test_create_user_accepts_zero_age",
                 "test_create_user_rejects_non_integer_age"] if has_tests else []
        return {
            "what_changed": " ".join(f"{c['file']}: {c['description']}" for c in applied),
            "why": "Negative ages are not meaningful. Validating in the model keeps the rule in one place, and the existing API "
                   "layer turns the ValidationError into a 422 response. The type check avoids a TypeError on non-numeric input.",
            "tests_added": tests,
            "limitations": ["Output came from the scripted offline provider, not an LLM.",
                            "Only the age rule was added; other fields keep their existing validation."],
        }
