"""Tests for forward problems — the direction with no oracle.

A forward task hands the model its inputs under `simulation/` and grades the
submission the same way an inverse task does. What has to hold: the engine
recognises the folder without an oracle, publishes no probe surface, refuses
probes with a comprehensible message, and grades identically.

Nothing here imports `mcp`.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))

import core  # noqa: E402


def write_forward_problem(
    root: Path,
    problem_id: str,
    golden: dict,
    inputs: dict[str, str] | None = None,
    prompt: str = "Run the case and report the result.",
    config: str | None = "direction: forward\n",
) -> Path:
    directory = root / problem_id
    (directory / "simulation").mkdir(parents=True)
    (directory / "golden").mkdir(parents=True)
    (directory / "problem.md").write_text(prompt)
    (directory / "golden" / "expected.json").write_text(json.dumps(golden))
    for name, content in (inputs or {"case.json": '{"n": 1}'}).items():
        path = directory / "simulation" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if config is not None:
        (directory / "config.yaml").write_text(config)
    return directory


class ForwardProblems(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="forward-tasks-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def session(self, problem_id: str) -> core.Session:
        return core.load_session(problem_id, [self.root])

    # -- discovery and direction ------------------------------------------ #

    def test_folder_without_oracle_is_discovered(self):
        write_forward_problem(self.root, "fwd", {"answer": 3.0, "tolerance": 0.01})
        self.assertIn("fwd", core.discover_problems([self.root]))

    def test_direction_detected_from_structure(self):
        directory = write_forward_problem(
            self.root, "fwd", {"answer": 3.0, "tolerance": 0.01}
        )
        self.assertEqual(core.detect_direction(directory), "forward")
        self.assertEqual(self.session("fwd").problem.direction, "forward")

    def test_structure_wins_over_config_metadata(self):
        # A folder with no oracle cannot be served as inverse whatever the
        # config claims; the validator reports the mismatch separately.
        directory = write_forward_problem(
            self.root, "fwd", {"answer": 1.0}, config="direction: inverse\n"
        )
        self.assertEqual(core.detect_direction(directory), "forward")

    def test_direction_read_from_config(self):
        directory = write_forward_problem(
            self.root, "fwd", {"answer": 1.0}, config="direction: forward  # trailing\n"
        )
        self.assertEqual(core.read_direction(directory), "forward")

    def test_missing_config_reads_as_none(self):
        directory = write_forward_problem(self.root, "fwd", {"answer": 1.0}, config=None)
        self.assertIsNone(core.read_direction(directory))

    # -- surface ------------------------------------------------------------ #

    def test_no_probe_surface_and_no_budget(self):
        write_forward_problem(self.root, "fwd", {"answer": 3.0, "tolerance": 0.01})
        session = self.session("fwd")
        self.assertEqual(session.problem.actions, [])
        self.assertIsNone(session.problem.budget_total)
        self.assertIsNone(session.remaining)

    def test_describe_lists_input_files(self):
        write_forward_problem(
            self.root,
            "fwd",
            {"answer": 3.0},
            inputs={"case.json": "{}", "mesh/grid.txt": "1 2 3"},
        )
        described = self.session("fwd").describe()
        self.assertEqual(described["direction"], "forward")
        self.assertEqual(described["input_files"], ["case.json", "mesh/grid.txt"])
        self.assertIn("no oracle", described["note"])

    def test_probing_a_forward_task_is_refused_clearly(self):
        write_forward_problem(self.root, "fwd", {"answer": 3.0})
        session = self.session("fwd")
        with self.assertRaises(core.UnknownAction) as caught:
            session.query("evaluate", {"x": 1})
        self.assertIn("forward task", str(caught.exception))

    def test_tool_guide_offers_submit_only(self):
        write_forward_problem(self.root, "fwd", {"answer": 3.0, "tolerance": 0.01})
        guide = core.render_tool_guide(self.session("fwd"))
        self.assertIn("submit_answer", guide)
        self.assertIn("case.json", guide)
        self.assertNotIn("query_oracle", guide)
        self.assertNotIn("Query budget", guide)

    # -- grading is unchanged ----------------------------------------------- #

    def test_correct_submission_scores_one(self):
        write_forward_problem(self.root, "fwd", {"answer": 3.0, "tolerance": 0.01})
        session = self.session("fwd")
        session.submit(3.004)
        self.assertEqual(session.grade()["subscores"]["correct"], 1.0)

    def test_answer_outside_tolerance_scores_zero(self):
        write_forward_problem(self.root, "fwd", {"answer": 3.0, "tolerance": 0.01})
        session = self.session("fwd")
        session.submit(2.38)
        self.assertEqual(session.grade()["subscores"]["correct"], 0.0)

    def test_no_submission_scores_zero(self):
        write_forward_problem(self.root, "fwd", {"answer": 3.0})
        grade = self.session("fwd").grade()
        self.assertEqual(grade["subscores"]["correct"], 0.0)
        self.assertIn("no answer submitted", grade["metadata"]["reason"])


class ReferenceForwardProblem(unittest.TestCase):
    """The shipped forward reference problem must stay solvable and trapped."""

    directory = REPO_ROOT / "problems" / "rod-heat-forward"

    def test_direction(self):
        self.assertEqual(core.detect_direction(self.directory), "forward")

    def test_intended_beats_shortcut_and_only_one_matches_golden(self):
        sys.path.insert(0, str(self.directory / "solution"))
        try:
            import importlib.util

            def load(name):
                spec = importlib.util.spec_from_file_location(
                    f"rodheat_{name}", self.directory / "solution" / f"{name}.py"
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module

            intended = load("main").solve(self.directory / "simulation")
            shortcut = load("shortcut").solve(self.directory / "simulation")
        finally:
            sys.path.remove(str(self.directory / "solution"))

        golden = json.loads((self.directory / "golden" / "expected.json").read_text())
        self.assertTrue(core.compare_answers(intended, golden)["correct"])
        self.assertFalse(core.compare_answers(shortcut, golden)["correct"])
        # The trap must be far outside tolerance, not marginally outside it.
        self.assertGreater(abs(intended - shortcut), 20 * golden["tolerance"])


if __name__ == "__main__":
    unittest.main()
