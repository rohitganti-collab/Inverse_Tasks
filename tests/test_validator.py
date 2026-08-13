"""Tests for tools/validate_problem.py.

The validator is the gate between "an expert wrote a problem" and "it runs on
Taiga", so its failure modes matter as much as the engine's. These tests build
deliberately broken problems and assert the validator catches each one.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402
import validate_problem as vp  # noqa: E402
from test_core import write_problem  # noqa: E402

# A seeded family, which is the shape the validator wants: the hidden values are
# a function of a per-episode seed, falling back to the authoring instance that
# golden/expected.json describes when no seed is set. A fixed-constant oracle
# grades against the same answer in every rollout, so a model that has seen the
# task once scores 1.0 with no probes — see FIXED_INSTANCE_ORACLE below.
GOOD_ORACLE = """
    import os
    import random

    class Oracle:
        M = 97
        BUDGET = 6
        ACTIONS = [
            {"name": "evaluate",
             "description": "Return the output for x.",
             "params": {"x": {"type": "integer", "required": True}}},
        ]

        def __init__(self, seed=None):
            raw = seed if seed is not None else os.environ.get("INVERSE_TASKS_SEED")
            if raw is None:
                self._A, self._B = 5, 2      # the authoring instance
            else:
                rng = random.Random(int(raw))
                self._A = rng.randrange(1, self.M)
                self._B = rng.randrange(0, self.M)

        def evaluate(self, x):
            return (self._A * x + self._B) % self.M
"""

FIXED_INSTANCE_ORACLE = """
    class Oracle:
        M = 97
        BUDGET = 6
        _A = 5
        _B = 2
        ACTIONS = [
            {"name": "evaluate",
             "description": "Return the output for x.",
             "params": {"x": {"type": "integer", "required": True}}},
        ]
        def evaluate(self, x):
            return (self._A * x + self._B) % self.M
"""

GOOD_INTENDED = """
    def solve(oracle):
        b = oracle.evaluate(0)
        y1 = oracle.evaluate(1)
        return [(y1 - b) % oracle.M, b]
"""

GOOD_SHORTCUT = """
    def solve(oracle):
        return [oracle.evaluate(1), 0]
"""


class ValidatorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="inverse-validator-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def build(
        self,
        problem_id: str = "demo",
        oracle_src: str = GOOD_ORACLE,
        golden: dict | None = None,
        intended: str | None = GOOD_INTENDED,
        shortcut: str | None = GOOD_SHORTCUT,
        prompt: str = "Report the pair.",
    ) -> Path:
        import textwrap

        directory = write_problem(
            self.root,
            problem_id,
            oracle_src,
            golden if golden is not None else {"answer": [5, 2], "tolerance": 0},
            prompt=prompt,
        )
        if intended or shortcut:
            (directory / "solution").mkdir(parents=True, exist_ok=True)
        if intended:
            (directory / "solution" / "main.py").write_text(textwrap.dedent(intended))
        if shortcut:
            (directory / "solution" / "shortcut.py").write_text(textwrap.dedent(shortcut))
        return directory

    def run_validator(self, problem_id: str = "demo") -> vp.Report:
        directory = self.root / problem_id
        return vp.validate(problem_id, directory, [self.root])

    def statuses(self, report: vp.Report, needle: str) -> list[str]:
        return [s for s, check, detail in report.rows if needle in check or needle in detail]


class TestHappyPath(ValidatorTestCase):
    def test_a_well_formed_problem_passes_cleanly(self):
        self.build()
        report = self.run_validator()
        self.assertFalse(report.failed, report.render())
        self.assertEqual([s for s, _, _ in report.rows if s == vp.WARN], [], report.render())

    def test_exit_code_is_zero_for_a_good_problem(self):
        self.build()
        self.assertEqual(vp.main(["--problems-dir", str(self.root)]), 0)

    def test_a_fixed_instance_oracle_is_flagged(self):
        """8/8 at 1.0 with zero variance is what this looks like in production."""
        self.build(oracle_src=FIXED_INSTANCE_ORACLE)
        report = self.run_validator()
        self.assertFalse(report.failed, report.render())  # advisory, not blocking
        self.assertEqual(self.statuses(report, "instance:"), [vp.WARN], report.render())

    def test_the_grade_payload_is_checked_for_the_answer(self):
        self.build()
        report = self.run_validator()
        self.assertEqual(self.statuses(report, "privacy:"), [vp.PASS], report.render())

    def test_observations_are_checked_for_transportability(self):
        self.build()
        report = self.run_validator()
        self.assertEqual(self.statuses(report, "transport:"), [vp.PASS], report.render())


class TestAnswerDisclosure(ValidatorTestCase):
    """An action that ends the task in one call must not pass validation."""

    GIVEAWAY = """
        class Oracle:
            M = 97
            BUDGET = 6
            ACTIONS = [
                {"name": "evaluate",
                 "params": {"x": {"type": "integer", "required": True}}},
                {"name": "calibrate",
                 "description": "Reference readout.",
                 "params": {}, "costs_budget": False},
            ]
            def evaluate(self, x):
                return (5 * x + 2) % self.M
            def calibrate(self):
                return [5, 2]
    """

    def test_an_action_returning_the_whole_answer_fails(self):
        self.build(oracle_src=self.GIVEAWAY)
        report = self.run_validator()
        self.assertIn(vp.FAIL, self.statuses(report, "does not disclose"), report.render())

    def test_a_component_in_an_observation_is_not_flagged(self):
        """evaluate(0) returning b is the intended path, not a leak."""
        self.build()
        report = self.run_validator()
        self.assertNotIn(vp.FAIL, self.statuses(report, "disclose"), report.render())


class TestToleranceDiscriminates(ValidatorTestCase):
    def test_a_tolerance_wider_than_the_answer_fails(self):
        self.build(golden={"answer": [5, 2], "tolerance": 100})
        report = self.run_validator()
        self.assertIn(vp.FAIL, self.statuses(report, "tolerance:"), report.render())

    def test_a_sane_tolerance_passes(self):
        self.build(golden={"answer": [5, 2], "tolerance": 1})
        report = self.run_validator()
        self.assertNotIn(vp.FAIL, self.statuses(report, "tolerance:"), report.render())


class TestCatchesBrokenTasks(ValidatorTestCase):
    def test_intended_solver_that_fails_is_a_failure(self):
        self.build(intended="def solve(oracle):\n    return [0, 0]\n")
        report = self.run_validator()
        self.assertTrue(report.failed)
        self.assertIn(vp.FAIL, self.statuses(report, "intended"))

    def test_intended_solver_that_crashes_is_a_failure(self):
        self.build(intended="def solve(oracle):\n    raise RuntimeError('boom')\n")
        report = self.run_validator()
        self.assertTrue(report.failed)
        self.assertIn(vp.FAIL, self.statuses(report, "intended"))

    def test_shortcut_that_passes_is_a_failure(self):
        # A trap that scores 1.0 doesn't discriminate, so the task is broken.
        self.build(shortcut=GOOD_INTENDED)
        report = self.run_validator()
        self.assertTrue(report.failed)
        self.assertIn(vp.FAIL, self.statuses(report, "shortcut"))

    def test_intended_solver_exceeding_budget_is_a_failure(self):
        self.build(
            oracle_src=GOOD_ORACLE.replace("BUDGET = 6", "BUDGET = 1"),
            intended=GOOD_INTENDED,
        )
        report = self.run_validator()
        self.assertTrue(report.failed)

    def test_unserviceable_declared_action_is_a_failure(self):
        # ACTIONS promises `question`, but query() cannot accept it.
        self.build(
            oracle_src="""
                class Oracle:
                    BUDGET = 3
                    ACTIONS = [
                        {"name": "hint",
                         "params": {"question": {"type": "string", "default": ""}},
                         "costs_budget": False},
                    ]
                    def query(self, mode, x=None):
                        return "hint text"
            """,
            intended=None,
            shortcut=None,
        )
        report = self.run_validator()
        self.assertTrue(report.failed)
        self.assertIn(vp.FAIL, self.statuses(report, "serviceable"))

    def test_answer_printed_in_the_prompt_is_a_failure(self):
        self.build(
            golden={"answer": [4271, 9182], "tolerance": 0},
            prompt="Report the pair. (Between you and me, a is 4271.)",
            intended=None,
            shortcut=None,
        )
        report = self.run_validator()
        self.assertTrue(report.failed)
        self.assertIn(vp.FAIL, self.statuses(report, "leakage"))

    def test_small_numbers_in_the_prompt_are_not_treated_as_leaks(self):
        # A modulus of 97 or an answer of 2 shows up in ordinary prose.
        self.build(prompt="Report the pair (a, b) for the mod 97 box, 2 constants.")
        report = self.run_validator()
        self.assertNotIn(vp.FAIL, self.statuses(report, "leakage"))

    def test_unenforced_budget_is_a_failure(self):
        self.build(
            oracle_src="""
                class Oracle:
                    BUDGET = 2
                    ACTIONS = [{"name": "probe"}]
                    def probe(self):
                        return 1
            """,
            intended=None,
            shortcut=None,
        )
        # The engine enforces BUDGET itself, so this must PASS — the check exists
        # to catch an oracle whose actions are all declared costs_budget=False.
        report = self.run_validator()
        self.assertIn(vp.PASS, self.statuses(report, "budget: enforced"))

    def test_budget_that_can_never_bind_is_flagged(self):
        self.build(
            oracle_src="""
                class Oracle:
                    BUDGET = 2
                    ACTIONS = [{"name": "probe", "costs_budget": False}]
                    def probe(self):
                        return 1
            """,
            intended=None,
            shortcut=None,
        )
        report = self.run_validator()
        self.assertIn(vp.WARN, self.statuses(report, "some action spends budget"))

    def test_golden_mismatching_declared_schema_is_a_failure(self):
        self.build(
            oracle_src=GOOD_ORACLE.replace(
                'ACTIONS = [',
                'ANSWER_SCHEMA = {"type": "array", "length": 3}\n        ACTIONS = [',
            ),
            intended=None,
            shortcut=None,
        )
        report = self.run_validator()
        self.assertTrue(report.failed)
        self.assertIn(vp.FAIL, self.statuses(report, "ANSWER_SCHEMA"))

    def test_misaligned_keys_are_a_failure(self):
        self.build(
            golden={"answer": [5, 2], "tolerance": 0, "keys": ["a", "b", "c"]},
            intended=None,
            shortcut=None,
        )
        report = self.run_validator()
        self.assertTrue(report.failed)

    def test_missing_solvers_only_warn(self):
        self.build(intended=None, shortcut=None)
        report = self.run_validator()
        self.assertFalse(report.failed)
        self.assertIn(vp.WARN, self.statuses(report, "intended"))
        self.assertIn(vp.WARN, self.statuses(report, "shortcut"))

    def test_unbudgeted_oracle_only_warns(self):
        self.build(
            oracle_src=GOOD_ORACLE.replace("BUDGET = 6", "pass"),
            intended=None,
            shortcut=None,
        )
        report = self.run_validator()
        self.assertFalse(report.failed)
        self.assertIn(vp.WARN, self.statuses(report, "BUDGET"))

    def test_method_hint_text_naming_the_fix_warns(self):
        self.build(
            oracle_src="""
                class Oracle:
                    BUDGET = 3
                    ACTIONS = [
                        {"name": "probe", "params": {"x": {"type": "integer", "required": True}}},
                        {"name": "hint", "costs_budget": False},
                    ]
                    def probe(self, x):
                        return x
                    def hint(self):
                        return "Try two adjacent inputs instead of far-apart ones."
            """,
            intended=None,
            shortcut=None,
        )
        report = self.run_validator()
        self.assertIn(vp.WARN, self.statuses(report, "may name the method"))


class TestOracleProxy(ValidatorTestCase):
    """The proxy is what expert-written solvers actually talk to."""

    def proxy(self, oracle_src: str = GOOD_ORACLE):
        self.build(oracle_src=oracle_src, intended=None, shortcut=None)
        session = core.load_session("demo", [self.root])
        return vp._OracleProxy(session), session

    def test_positional_arguments_work(self):
        proxy, _ = self.proxy()
        self.assertEqual(proxy.evaluate(0), 2)

    def test_keyword_arguments_work(self):
        proxy, _ = self.proxy()
        self.assertEqual(proxy.evaluate(x=0), 2)

    def test_query_dispatcher_style_works(self):
        proxy, _ = self.proxy()
        self.assertEqual(proxy.query("evaluate", x=1), 7)

    def test_query_dispatcher_accepts_positional_args(self):
        proxy, _ = self.proxy()
        self.assertEqual(proxy.query("evaluate", 1), 7)

    def test_calls_are_metered_like_the_model(self):
        proxy, session = self.proxy()
        proxy.evaluate(0)
        proxy.evaluate(1)
        self.assertEqual(session.calls_used, 2)

    def test_budget_applies_to_solvers_too(self):
        proxy, _ = self.proxy(GOOD_ORACLE.replace("BUDGET = 6", "BUDGET = 1"))
        proxy.evaluate(0)
        with self.assertRaises(core.BudgetExceeded):
            proxy.evaluate(1)

    def test_public_constants_pass_through(self):
        proxy, _ = self.proxy()
        self.assertEqual(proxy.M, 97)
        self.assertEqual(proxy.BUDGET, 6)

    def test_private_ground_truth_is_unreachable(self):
        proxy, _ = self.proxy()
        with self.assertRaisesRegex(AttributeError, "hidden from solvers"):
            proxy._A

    def test_undeclared_method_is_unreachable(self):
        proxy, _ = self.proxy(
            GOOD_ORACLE + "\n        def backdoor(self):\n            return 'oops'\n"
        )
        with self.assertRaisesRegex(AttributeError, "not a declared action"):
            proxy.backdoor

    def test_too_many_positional_arguments_is_an_error(self):
        proxy, _ = self.proxy()
        with self.assertRaisesRegex(TypeError, "at most 1 argument"):
            proxy.evaluate(1, 2)

    def test_duplicate_argument_is_an_error(self):
        proxy, _ = self.proxy()
        with self.assertRaisesRegex(TypeError, "multiple values"):
            proxy.evaluate(1, x=2)


class TestCLI(ValidatorTestCase):
    def test_unknown_problem_id_exits_nonzero(self):
        self.build()
        self.assertEqual(
            vp.main(["nope", "--problems-dir", str(self.root)]), 1
        )

    def test_empty_problems_dir_exits_nonzero(self):
        empty = Path(tempfile.mkdtemp(prefix="inverse-empty-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        self.assertEqual(vp.main(["--problems-dir", str(empty)]), 1)

    def test_broken_problem_exits_nonzero(self):
        self.build(intended="def solve(oracle):\n    return [0, 0]\n")
        self.assertEqual(vp.main(["--problems-dir", str(self.root)]), 1)


class TestShippedProblemValidates(unittest.TestCase):
    def test_modular_black_box_has_no_failures(self):
        problems = core.discover_problems()
        report = vp.validate("modular-black-box", problems["modular-black-box"], None)
        self.assertFalse(report.failed, report.render())


if __name__ == "__main__":
    unittest.main(verbosity=2)
