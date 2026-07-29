"""Tests for the oracle-agnostic engine.

Run with:  python3 -m unittest discover -s tests -v

These use throwaway problem folders written to a temp dir, each with a
deliberately *different* oracle shape, because the whole point of the engine is
that it doesn't care what an expert's oracle looks like. Nothing here imports
`mcp`, so the suite runs anywhere python3 does.
"""
from __future__ import annotations

import inspect
import json
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))

import core  # noqa: E402


def write_problem(
    root: Path,
    problem_id: str,
    oracle_src: str,
    golden: dict,
    prompt: str = "Recover the hidden values.",
    grader_src: str | None = None,
) -> Path:
    directory = root / problem_id
    (directory / "oracle").mkdir(parents=True)
    (directory / "golden").mkdir(parents=True)
    (directory / "problem.md").write_text(prompt)
    (directory / "oracle" / "setup.py").write_text(textwrap.dedent(oracle_src))
    (directory / "golden" / "expected.json").write_text(json.dumps(golden))
    if grader_src is not None:
        (directory / "grader").mkdir(parents=True)
        (directory / "grader" / "grade.py").write_text(textwrap.dedent(grader_src))
    return directory


class TempProblems(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="inverse-tasks-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def session(self, problem_id: str) -> core.Session:
        return core.load_session(problem_id, [self.root])


# --------------------------------------------------------------------------- #
# Oracle shape diversity — the core genericity claim
# --------------------------------------------------------------------------- #


class TestOracleShapes(TempProblems):
    def test_method_based_oracle_with_declared_actions(self):
        write_problem(
            self.root,
            "methods",
            """
            class Oracle:
                BUDGET = 4
                ACTIONS = [
                    {"name": "probe",
                     "description": "Probe at t.",
                     "params": {"t": {"type": "number", "required": True}}},
                    {"name": "hint", "description": "Free hint.", "costs_budget": False},
                ]
                def probe(self, t):
                    return 3.0 * t + 1.0
                def hint(self):
                    return "no comment"
            """,
            {"answer": [3.0, 1.0], "tolerance": 1e-9},
        )
        s = self.session("methods")
        self.assertEqual([a["name"] for a in s.problem.actions], ["probe", "hint"])
        self.assertTrue(s.problem.actions_declared)
        self.assertEqual(s.query("probe", {"t": 2}), 7.0)
        self.assertEqual(s.calls_used, 1)
        s.query("hint", {})
        self.assertEqual(s.calls_used, 1, "free actions must not spend budget")

    def test_query_only_oracle_is_serviced_via_dispatcher(self):
        write_problem(
            self.root,
            "querydispatch",
            """
            class Oracle:
                BUDGET = 3
                ACTIONS = {
                    "measure": {"params": {"n": {"type": "integer", "required": True}}},
                }
                def query(self, mode, **kw):
                    if mode == "measure":
                        return kw["n"] * 5
                    raise ValueError(mode)
            """,
            {"answer": 5, "tolerance": 0},
        )
        s = self.session("querydispatch")
        self.assertEqual(s.query("measure", {"n": 3}), 15)

    def test_undeclared_oracle_falls_back_to_introspection(self):
        write_problem(
            self.root,
            "introspected",
            """
            class Oracle:
                BUDGET = 2
                def spin(self, k: int, label: str = "x"):
                    "Spin it."
                    return f"{label}:{k}"
                def _hidden(self):
                    return "never exposed"
            """,
            {"answer": "x:1", "tolerance": 0},
        )
        s = self.session("introspected")
        names = [a["name"] for a in s.problem.actions]
        self.assertEqual(names, ["spin"])
        self.assertNotIn("_hidden", names)
        action = s.problem.action("spin")
        self.assertEqual(
            {p["name"]: p["type"] for p in action["params"]},
            {"k": "integer", "label": "string"},
        )
        self.assertEqual(s.query("spin", {"k": 1}), "x:1")

    def test_bare_query_oracle_allows_undeclared_passthrough(self):
        write_problem(
            self.root,
            "bare",
            """
            class Oracle:
                def query(self, mode, **kw):
                    return {"mode": mode, "kw": kw}
            """,
            {"answer": "anything", "tolerance": 0},
        )
        s = self.session("bare")
        self.assertFalse(s.problem.actions_declared)
        self.assertIsNone(s.problem.budget_total, "no BUDGET means unbudgeted")
        self.assertEqual(s.query("whatever", {"a": 1}), {"mode": "whatever", "kw": {"a": 1}})

    def test_oracle_without_any_probe_surface_is_rejected(self):
        write_problem(
            self.root,
            "useless",
            """
            class Oracle:
                BUDGET = 1
            """,
            {"answer": 1},
        )
        with self.assertRaises(core.OracleContractError):
            self.session("useless")

    def test_missing_oracle_class_is_rejected(self):
        write_problem(
            self.root,
            "noclass",
            """
            class NotAnOracle:
                pass
            """,
            {"answer": 1},
        )
        with self.assertRaisesRegex(core.OracleContractError, "no class named `Oracle`"):
            self.session("noclass")

    def test_reserved_action_name_is_rejected(self):
        write_problem(
            self.root,
            "reserved",
            """
            class Oracle:
                ACTIONS = [{"name": "grade_problem"}]
                def query(self, mode, **kw):
                    return 1
            """,
            {"answer": 1},
        )
        with self.assertRaisesRegex(core.OracleContractError, "reserved"):
            self.session("reserved")

    def test_fresh_oracle_per_session(self):
        write_problem(
            self.root,
            "stateful",
            """
            class Oracle:
                BUDGET = 10
                ACTIONS = [{"name": "tick"}]
                def __init__(self):
                    self._n = 0
                def tick(self):
                    self._n += 1
                    return self._n
            """,
            {"answer": 1},
        )
        first = self.session("stateful")
        self.assertEqual(first.query("tick", {}), 1)
        self.assertEqual(first.query("tick", {}), 2)
        second = self.session("stateful")
        self.assertEqual(second.query("tick", {}), 1, "state must not leak between attempts")


# --------------------------------------------------------------------------- #
# Budget accounting
# --------------------------------------------------------------------------- #


class TestBudget(TempProblems):
    ORACLE = """
        class Oracle:
            BUDGET = 2
            ACTIONS = [
                {"name": "cost", "params": {"x": {"type": "integer", "required": True}}},
                {"name": "free", "costs_budget": False},
            ]
            def cost(self, x):
                if x < 0:
                    raise ValueError("negative")
                return x
            def free(self):
                return "free"
    """

    def setUp(self) -> None:
        super().setUp()
        write_problem(self.root, "budget", self.ORACLE, {"answer": 1})

    def test_budget_is_enforced_by_the_engine(self):
        s = self.session("budget")
        s.query("cost", {"x": 1})
        s.query("cost", {"x": 2})
        self.assertEqual(s.remaining, 0)
        with self.assertRaises(core.BudgetExceeded):
            s.query("cost", {"x": 3})

    def test_free_actions_remain_available_after_budget_exhaustion(self):
        s = self.session("budget")
        s.query("cost", {"x": 1})
        s.query("cost", {"x": 2})
        self.assertEqual(s.query("free", {}), "free")

    def test_a_raising_oracle_still_spends_its_call(self):
        # Otherwise a solver could probe for free by deliberately erroring.
        s = self.session("budget")
        with self.assertRaises(ValueError):
            s.query("cost", {"x": -1})
        self.assertEqual(s.calls_used, 1)

    def test_unknown_action_is_rejected_without_spending_budget(self):
        s = self.session("budget")
        with self.assertRaises(core.UnknownAction):
            s.query("nonexistent", {})
        self.assertEqual(s.calls_used, 0)

    def test_missing_required_param_is_rejected_without_spending_budget(self):
        s = self.session("budget")
        with self.assertRaises(core.UnknownAction):
            s.query("cost", {})
        self.assertEqual(s.calls_used, 0)

    def test_unexpected_param_is_rejected(self):
        s = self.session("budget")
        with self.assertRaisesRegex(core.UnknownAction, "unexpected"):
            s.query("cost", {"x": 1, "y": 2})

    def test_stringy_argument_is_coerced(self):
        s = self.session("budget")
        self.assertEqual(s.query("cost", {"x": "7"}), 7)


# --------------------------------------------------------------------------- #
# Answer parsing, shape checks, comparison
# --------------------------------------------------------------------------- #


class TestAnswerParsing(unittest.TestCase):
    def test_json_forms(self):
        self.assertEqual(core.parse_answer("[23, 58]"), [23, 58])
        self.assertEqual(core.parse_answer('{"a": 23, "b": 58}'), {"a": 23, "b": 58})
        self.assertEqual(core.parse_answer("42"), 42)

    def test_code_fences_are_stripped(self):
        self.assertEqual(core.parse_answer("```json\n[23, 58]\n```"), [23, 58])
        self.assertEqual(core.parse_answer("```\n[1, 2]\n```"), [1, 2])

    def test_python_literals(self):
        self.assertEqual(core.parse_answer("(23, 58)"), [23, 58])
        self.assertEqual(core.parse_answer("{'a': 1}"), {"a": 1})

    def test_prose_is_not_scraped_for_numbers(self):
        # Reinterpreting prose could turn a wrong answer into a passing one.
        self.assertEqual(core.parse_answer("a is 23 and b is 58"), "a is 23 and b is 58")


class TestComparison(unittest.TestCase):
    GOLDEN = {"answer": [23, 58], "tolerance": 0, "keys": ["a", "b"]}

    def test_exact_match(self):
        self.assertTrue(core.compare_answers([23, 58], self.GOLDEN)["correct"])

    def test_dict_submission_accepted_when_golden_names_keys(self):
        result = core.compare_answers({"a": 23, "b": 58}, self.GOLDEN)
        self.assertTrue(result["correct"])

    def test_order_matters(self):
        self.assertFalse(core.compare_answers([58, 23], self.GOLDEN)["correct"])

    def test_near_miss_scores_zero_under_binary_scoring(self):
        result = core.compare_answers([-1, 104], self.GOLDEN)
        self.assertFalse(result["correct"])
        self.assertEqual(result["score"], 0.0)

    def test_half_right_scores_zero_under_binary_scoring(self):
        result = core.compare_answers([23, 0], self.GOLDEN)
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["matches"], 1)

    def test_partial_scoring_is_opt_in(self):
        golden = dict(self.GOLDEN, scoring="partial")
        self.assertEqual(core.compare_answers([23, 0], golden)["score"], 0.5)

    def test_wrong_arity_is_never_partially_right(self):
        golden = dict(self.GOLDEN, scoring="partial")
        result = core.compare_answers([23], golden)
        self.assertEqual(result["score"], 0.0)

    def test_tolerance_applies_to_numbers(self):
        golden = {"answer": [1.0], "tolerance": 0.05}
        self.assertTrue(core.compare_answers([1.02], golden)["correct"])
        self.assertFalse(core.compare_answers([1.2], golden)["correct"])

    def test_dict_golden(self):
        golden = {"answer": {"k": 2, "n": 5}, "tolerance": 0}
        self.assertTrue(core.compare_answers({"k": 2, "n": 5}, golden)["correct"])
        self.assertFalse(core.compare_answers({"k": 2}, golden)["correct"])

    def test_string_golden_ignores_surrounding_whitespace(self):
        golden = {"answer": "michaelis-menten", "tolerance": 0}
        self.assertTrue(core.compare_answers("  michaelis-menten ", golden)["correct"])
        self.assertFalse(core.compare_answers("hill", golden)["correct"])

    def test_nested_golden(self):
        golden = {"answer": [[1, 2], [3, 4]], "tolerance": 0}
        self.assertTrue(core.compare_answers([[1, 2], [3, 4]], golden)["correct"])
        self.assertFalse(core.compare_answers([[1, 2], [3, 5]], golden)["correct"])


class TestShapeChecks(unittest.TestCase):
    def test_length_mismatch_warns(self):
        warnings = core.check_answer_shape([1], {"type": "array", "length": 2})
        self.assertTrue(any("2 element" in w for w in warnings))

    def test_type_mismatch_warns(self):
        warnings = core.check_answer_shape("nope", {"type": "array", "length": 2})
        self.assertTrue(any("array" in w for w in warnings))

    def test_int_satisfies_number(self):
        self.assertEqual(core.check_answer_shape(3, {"type": "number"}), [])

    def test_missing_dict_keys_warn(self):
        warnings = core.check_answer_shape({"a": 1}, {"type": "object", "keys": ["a", "b"]})
        self.assertTrue(any("b" in w for w in warnings))

    def test_good_answer_has_no_warnings(self):
        self.assertEqual(
            core.check_answer_shape([23, 58], {"type": "array", "length": 2}), []
        )


# --------------------------------------------------------------------------- #
# Submission + grading
# --------------------------------------------------------------------------- #


class TestSubmissionAndGrading(TempProblems):
    ORACLE = """
        class Oracle:
            BUDGET = 5
            ACTIONS = [{"name": "peek", "params": {"i": {"type": "integer", "required": True}}}]
            def peek(self, i):
                return i
    """

    def setUp(self) -> None:
        super().setUp()
        write_problem(
            self.root,
            "grading",
            self.ORACLE,
            {"answer": [7, 9], "tolerance": 0, "keys": ["p", "q"]},
        )

    def test_no_submission_scores_zero(self):
        grade = self.session("grading").grade()
        self.assertEqual(grade["subscores"]["correct"], 0.0)
        self.assertEqual(grade["metadata"]["reason"], "no answer submitted")

    def test_correct_submission_scores_one(self):
        s = self.session("grading")
        s.submit("[7, 9]")
        grade = s.grade()
        self.assertEqual(grade["subscores"]["correct"], 1.0)
        self.assertEqual(grade["weights"], {"correct": 1.0})

    def test_resubmission_replaces_the_previous_answer(self):
        s = self.session("grading")
        s.submit("[1, 2]")
        s.submit("[7, 9]")
        self.assertEqual(s.grade()["subscores"]["correct"], 1.0)

    def test_submit_returns_shape_warnings_without_revealing_the_answer(self):
        s = self.session("grading")
        result = s.submit("[7]")
        self.assertTrue(result["warnings"])
        self.assertNotIn("9", json.dumps(result["answer_shape"]))

    def test_grade_metadata_records_the_probe_log(self):
        s = self.session("grading")
        s.query("peek", {"i": 3})
        s.submit("[7, 9]")
        metadata = s.grade()["metadata"]
        self.assertEqual(metadata["budget_used"], 1)
        self.assertEqual(metadata["call_log"][0]["action"], "peek")
        self.assertEqual(metadata["call_log"][0]["observation"], 3)

    def test_custom_grader_overrides_default_comparison(self):
        write_problem(
            self.root,
            "customgrade",
            self.ORACLE,
            {"answer": [7, 9], "tolerance": 0},
            grader_src="""
            def grade(submission, expected, **kwargs):
                # Award credit for getting the first element only.
                ok = isinstance(submission, list) and submission[:1] == expected[:1]
                return {
                    "subscores": {"first": 1.0 if ok else 0.0},
                    "weights": {"first": 1.0},
                    "metadata": {"custom": True},
                }
            """,
        )
        s = self.session("customgrade")
        s.submit("[7, 0]")
        grade = s.grade()
        self.assertEqual(grade["subscores"], {"first": 1.0})
        self.assertTrue(grade["metadata"]["custom"])

    def test_custom_grader_may_return_a_bare_float(self):
        write_problem(
            self.root,
            "floatgrade",
            self.ORACLE,
            {"answer": [7, 9], "tolerance": 0},
            grader_src="def grade(**kwargs):\n    return 0.25\n",
        )
        s = self.session("floatgrade")
        s.submit("[0, 0]")
        self.assertEqual(s.grade()["subscores"]["correct"], 0.25)

    def test_scores_are_clamped_to_the_unit_interval(self):
        write_problem(
            self.root,
            "hugegrade",
            self.ORACLE,
            {"answer": [7, 9], "tolerance": 0},
            grader_src="def grade(**kwargs):\n    return 42.0\n",
        )
        s = self.session("hugegrade")
        s.submit("[7, 9]")
        self.assertEqual(s.grade()["subscores"]["correct"], 1.0)


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


class TestDiscovery(TempProblems):
    def test_templates_and_dotfiles_are_not_problems(self):
        write_problem(self.root, "real", "class Oracle:\n    def query(self, m, **k):\n        return 1\n", {"answer": 1})
        write_problem(self.root, "_template", "class Oracle:\n    def query(self, m, **k):\n        return 1\n", {"answer": 1})
        write_problem(self.root, ".hidden", "class Oracle:\n    def query(self, m, **k):\n        return 1\n", {"answer": 1})
        self.assertEqual(sorted(core.discover_problems([self.root])), ["real"])

    def test_directory_without_problem_md_is_ignored(self):
        (self.root / "notaproblem").mkdir()
        self.assertEqual(core.discover_problems([self.root]), {})

    def test_unknown_problem_id_lists_what_is_available(self):
        write_problem(self.root, "only", "class Oracle:\n    def query(self, m, **k):\n        return 1\n", {"answer": 1})
        with self.assertRaisesRegex(core.ProblemNotFound, "only"):
            core.load_session("missing", [self.root])

    def test_earlier_roots_win_on_collision(self):
        # Mirrors a preloaded-files mount shadowing a baked-in problem.
        overlay = Path(tempfile.mkdtemp(prefix="inverse-overlay-"))
        self.addCleanup(shutil.rmtree, overlay, ignore_errors=True)
        write_problem(self.root, "dup", "class Oracle:\n    def query(self, m, **k):\n        return 'baked'\n", {"answer": 1})
        write_problem(overlay, "dup", "class Oracle:\n    def query(self, m, **k):\n        return 'mounted'\n", {"answer": 1})
        session = core.load_session("dup", [overlay, self.root])
        self.assertEqual(session.query("anything", {}), "mounted")


# --------------------------------------------------------------------------- #
# Synthesised tool signatures (what FastMCP introspects in bound mode)
# --------------------------------------------------------------------------- #


class TestSignatureSynthesis(unittest.TestCase):
    def synth(self, raw):
        calls = []
        action = core._normalise_action(raw)
        fn = core.synthesise_action_function(
            action, lambda name, params: calls.append((name, params)) or "ok"
        )
        return fn, calls

    def test_required_and_optional_params_become_a_real_signature(self):
        fn, calls = self.synth(
            {
                "name": "evaluate",
                "description": "Evaluate at x.",
                "params": {
                    "x": {"type": "integer", "required": True},
                    "label": {"type": "string", "default": "hi"},
                },
            }
        )
        self.assertEqual(fn.__name__, "evaluate")
        sig = inspect.signature(fn)
        self.assertEqual(list(sig.parameters), ["x", "label"])
        self.assertIs(sig.parameters["x"].annotation, int)
        self.assertIs(sig.parameters["label"].annotation, str)
        self.assertEqual(sig.parameters["label"].default, "hi")
        self.assertEqual(sig.parameters["x"].default, inspect.Parameter.empty)

        self.assertEqual(fn(5), "ok")
        self.assertEqual(calls, [("evaluate", {"x": 5, "label": "hi"})])

    def test_description_becomes_the_docstring_with_budget_note(self):
        fn, _ = self.synth({"name": "probe", "description": "Probe it.", "costs_budget": True})
        self.assertIn("Probe it.", fn.__doc__)
        self.assertIn("spends one unit", fn.__doc__)

        free, _ = self.synth({"name": "hint", "description": "Hint.", "costs_budget": False})
        self.assertIn("does not spend", free.__doc__)

    def test_required_params_are_ordered_before_optional_ones(self):
        # Otherwise the generated signature would be a syntax error.
        fn, _ = self.synth(
            {
                "name": "mixed",
                "params": {
                    "opt": {"type": "string", "default": ""},
                    "req": {"type": "integer", "required": True},
                },
            }
        )
        self.assertEqual(list(inspect.signature(fn).parameters), ["req", "opt"])

    def test_every_supported_type_synthesises(self):
        for json_type in core.JSON_TYPE_TO_PY:
            fn, _ = self.synth({"name": "t", "params": {"v": {"type": json_type, "required": True}}})
            self.assertIn("v", inspect.signature(fn).parameters)


class TestActionNormalisation(unittest.TestCase):
    def test_shorthand_declarations(self):
        action = core._normalise_action({"name": "f", "params": {"x": "integer", "y": int}})
        self.assertEqual({p["name"]: p["type"] for p in action["params"]}, {"x": "integer", "y": "integer"})

    def test_bare_string_action(self):
        self.assertEqual(core._normalise_action("ping")["name"], "ping")

    def test_default_implies_optional(self):
        action = core._normalise_action({"name": "f", "params": {"x": {"type": "integer", "default": 0}}})
        self.assertFalse(action["params"][0]["required"])

    def test_unsupported_type_is_rejected(self):
        with self.assertRaisesRegex(core.OracleContractError, "unsupported type"):
            core._normalise_action({"name": "f", "params": {"x": {"type": "complex"}}})

    def test_invalid_identifier_is_rejected(self):
        with self.assertRaisesRegex(core.OracleContractError, "identifier"):
            core._normalise_action({"name": "not a name"})

    def test_scaffold_prefix_is_rejected(self):
        with self.assertRaisesRegex(core.OracleContractError, "reserved"):
            core._normalise_action({"name": "_scaffold_sneaky"})


class TestJsonable(unittest.TestCase):
    def test_tuples_and_sets_become_lists(self):
        self.assertEqual(core._jsonable((1, 2)), [1, 2])
        self.assertEqual(sorted(core._jsonable({1, 2})), [1, 2])

    def test_unknown_objects_stringify(self):
        class Weird:
            def __repr__(self):
                return "<weird>"

        self.assertEqual(core._jsonable(Weird()), "<weird>")

    def test_objects_exposing_tolist_are_unwrapped(self):
        class FakeArray:
            def tolist(self):
                return [1, 2, 3]

        self.assertEqual(core._jsonable(FakeArray()), [1, 2, 3])

    def test_result_is_json_serialisable(self):
        json.dumps(core._jsonable({"a": (1, 2), "b": {3, 4}}))


# --------------------------------------------------------------------------- #
# The shipped sample problem, end to end
# --------------------------------------------------------------------------- #


class TestShippedSampleProblem(unittest.TestCase):
    PROBLEM_ID = "modular-black-box"

    def session(self):
        return core.load_session(self.PROBLEM_ID)

    def test_it_is_discoverable(self):
        self.assertIn(self.PROBLEM_ID, core.discover_problems())

    def test_declared_actions_match_the_prompt(self):
        s = self.session()
        self.assertEqual([a["name"] for a in s.problem.actions], ["evaluate", "help"])
        prompt = s.problem.prompt
        self.assertIn("evaluate(x)", prompt)
        self.assertIn("help(question)", prompt)

    def test_the_intended_path_solves_it_within_budget(self):
        s = self.session()
        b = s.query("evaluate", {"x": 0})
        y1 = s.query("evaluate", {"x": 1})
        a = (y1 - b) % s.problem.oracle.M
        s.submit(json.dumps([a, b]))
        self.assertEqual(s.grade()["subscores"]["correct"], 1.0)
        self.assertLessEqual(s.calls_used, s.problem.budget_total)

    def test_the_documented_near_miss_fails(self):
        s = self.session()
        y10 = s.query("evaluate", {"x": 10})
        y30 = s.query("evaluate", {"x": 30})
        a = round((y30 - y10) / 20)
        s.submit(json.dumps([a, y10 - a * 10]))
        self.assertEqual(s.grade()["subscores"]["correct"], 0.0)

    def test_help_is_free_and_hides_the_constants(self):
        s = self.session()
        hint = s.query("help", {"question": "anything"})
        self.assertEqual(s.calls_used, 0)
        self.assertNotIn("23", str(hint))
        self.assertNotIn("58", str(hint))

    def test_the_undeclared_noisy_mode_is_not_exposed(self):
        s = self.session()
        with self.assertRaises(core.UnknownAction):
            s.query("sample", {"x": 1})

    def test_answer_shape_does_not_leak_the_answer(self):
        shape = json.dumps(self.session().problem.answer_shape())
        self.assertNotIn("23", shape)
        self.assertNotIn("58", shape)


if __name__ == "__main__":
    unittest.main(verbosity=2)
