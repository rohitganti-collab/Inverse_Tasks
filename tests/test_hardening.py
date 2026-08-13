"""Regression tests for defects found in shipped inverse-task environments.

Every test here corresponds to something that actually happened on Taiga, in
the `rl_gym-inverse_tasks` image or a problem served by it. They are grouped
here rather than scattered through the other suites so the reason each check
exists stays attached to it — the failure modes are cheap to reintroduce and
expensive to notice, because in three of the four cases the task still *looked*
like it worked.

  1. `query_oracle` was annotated `-> str | int | dict`. FastMCP derives its
     output schema from the annotation, so an oracle returning a float failed
     validation on 100% of readings; the value reached the model only inside the
     error string. Every run still scored 1.0, because the models parsed the
     number out of the error text.

  2. The grade payload carried the golden answer, and Taiga writes grade output
     to `/workdir/app.log`, which is world-readable while solver tools run as
     uid 1000. With `grade_problem` reachable, that is a four-step exploit:
     submit a throwaway, grade, read the log, resubmit. Verified full credit
     with zero oracle probes.

  3. Hidden parameters were hardcoded, so the correct submission was the same
     constant array in every episode — 8/8 runs at 1.0 with zero variance.

  4. Attempt state and the submission handoff lived at predictable paths under
     world-writable `/tmp`, where a solver can pre-create them.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402

from test_core import write_problem  # noqa: E402

# `server` imports FastMCP at module scope. The suite runs without the real
# `mcp` package, so install the same stand-in test_server uses before importing
# it — test discovery order must not decide whether these tests can run.
from test_server import install_mcp_stub  # noqa: E402

install_mcp_stub()

import server  # noqa: E402

TAIGA_ENV = {"INVERSE_TASKS_RUNTIME": "taiga"}

# A float the deployed image could not return: 17 significant digits, so a
# lossy round-trip through the transport shows up as an inequality.
PRECISE = 1.3362473561192243


class HardeningCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="inverse-tasks-hardening-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def session(self, problem_id: str) -> core.Session:
        return core.load_session(problem_id, [self.root])


# --------------------------------------------------------------------------- #
# 1. Float observations must survive the transport
# --------------------------------------------------------------------------- #


class FloatObservations(HardeningCase):
    """A physics oracle returns floats. That has to be an ordinary result."""

    ORACLE = f"""
        class Oracle:
            BUDGET = 12
            ACTIONS = [
                {{"name": "measure",
                  "params": {{"x": {{"type": "number"}}}},
                  "description": "Read the bench."}},
            ]
            def measure(self, x):
                return {PRECISE} * x
        """

    def setUp(self) -> None:
        super().setUp()
        write_problem(self.root, "bench", self.ORACLE, {"answer": [1], "tolerance": 0})

    def test_float_observation_reaches_the_caller_unchanged(self) -> None:
        observation = self.session("bench").query("measure", {"x": 1.0})
        self.assertIsInstance(observation, float)
        self.assertEqual(observation, PRECISE)

    def test_float_observation_renders_at_full_precision(self) -> None:
        """The rendered form must round-trip: no truncation, no error wrapper."""
        rendered = server._dump(PRECISE)
        self.assertNotIn("validation error", rendered.lower())
        self.assertEqual(json.loads(rendered), PRECISE)

    def test_declared_number_params_accept_floats(self) -> None:
        session = self.session("bench")
        self.assertAlmostEqual(session.query("measure", {"x": 2.5}), PRECISE * 2.5)

    def test_a_raising_oracle_still_spends_budget(self) -> None:
        """No free probing by inducing errors."""
        write_problem(
            self.root,
            "explodes",
            """
            class Oracle:
                BUDGET = 3
                ACTIONS = [{"name": "boom", "params": {}}]
                def boom(self):
                    raise RuntimeError("bench offline")
            """,
            {"answer": 1, "tolerance": 0},
        )
        session = self.session("explodes")
        with self.assertRaises(RuntimeError):
            session.query("boom", {})
        self.assertEqual(session.calls_used, 1)


# --------------------------------------------------------------------------- #
# 2. The grade payload must never carry the answer
# --------------------------------------------------------------------------- #


class GradeMetadataLeakage(HardeningCase):
    """Taiga logs the grade payload somewhere the model can read it."""

    ORACLE = """
        class Oracle:
            BUDGET = 4
            ACTIONS = [{"name": "peek", "params": {}}]
            def peek(self):
                return 1
        """
    GOLDEN_ANSWER = [1784, 1330, 840, 935]

    def setUp(self) -> None:
        super().setUp()
        write_problem(
            self.root,
            "shg",
            self.ORACLE,
            {"answer": self.GOLDEN_ANSWER, "tolerance": 2},
        )

    def _grade(self, submission):
        session = self.session("shg")
        session.submit(submission)
        return session.grade()

    def test_taiga_runtime_never_emits_the_answer(self) -> None:
        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            grade = self._grade([0, 0, 0, 0])
        blob = json.dumps(grade["metadata"], sort_keys=True)
        self.assertNotIn("expected", grade["metadata"])
        for value in self.GOLDEN_ANSWER:
            self.assertNotIn(
                str(value),
                blob,
                f"golden component {value} leaked into grade metadata: {blob}",
            )

    def test_per_element_details_are_redacted(self) -> None:
        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            grade = self._grade([0, 0, 0, 0])
        for item in grade["metadata"].get("details") or []:
            self.assertNotIn("expected", item)
            # Still useful: which element was wrong, and what we sent.
            self.assertIn("match", item)

    def test_unsubmitted_grade_is_also_clean(self) -> None:
        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            grade = self.session("shg").grade()
        blob = json.dumps(grade["metadata"], sort_keys=True)
        for value in self.GOLDEN_ANSWER:
            self.assertNotIn(str(value), blob)

    def test_custom_grader_metadata_is_scrubbed_too(self) -> None:
        """An expert's grader must not be able to reopen the hole."""
        write_problem(
            self.root,
            "chatty",
            self.ORACLE,
            {"answer": self.GOLDEN_ANSWER, "tolerance": 0},
            grader_src="""
            def grade(submission, expected, **kwargs):
                return {
                    "subscores": {"correct": 0.0},
                    "weights": {"correct": 1.0},
                    "metadata": {"expected": expected, "hint": "look at metadata"},
                }
            """,
        )
        session = self.session("chatty")
        session.submit([0, 0, 0, 0])
        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            grade = session.grade()
        self.assertNotIn("expected", grade["metadata"])

    def test_authoring_runs_still_see_the_answer(self) -> None:
        """Redaction is a runtime guard, not a debugging tax."""
        with mock.patch.dict(
            os.environ, {"INVERSE_TASKS_RUNTIME": "build"}, clear=False
        ):
            grade = self._grade([0, 0, 0, 0])
        self.assertEqual(grade["metadata"]["expected"], self.GOLDEN_ANSWER)

    def test_correct_answers_still_score_one(self) -> None:
        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            grade = self._grade(self.GOLDEN_ANSWER)
        self.assertEqual(grade["subscores"]["correct"], 1.0)

    def test_wrong_answers_still_score_zero(self) -> None:
        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            grade = self._grade([1, 2, 3, 4])
        self.assertEqual(grade["subscores"]["correct"], 0.0)


# --------------------------------------------------------------------------- #
# 3. Fingerprint: how a fixed-instance task gets caught
# --------------------------------------------------------------------------- #


class AnswerFingerprint(HardeningCase):
    def test_fingerprint_is_stable_and_non_invertible(self) -> None:
        answer = [1784, 1330, 840, 935]
        digest = core.answer_fingerprint(answer)
        self.assertEqual(digest, core.answer_fingerprint(list(answer)))
        for value in answer:
            self.assertNotIn(str(value), digest)

    def test_different_instances_fingerprint_differently(self) -> None:
        """Two rollouts sharing a fingerprint means the instance never varied."""
        self.assertNotEqual(
            core.answer_fingerprint([1784, 1330, 840, 935]),
            core.answer_fingerprint([1785, 1330, 840, 935]),
        )

    def test_fingerprint_is_reported_in_the_grade(self) -> None:
        write_problem(
            self.root,
            "fp",
            """
            class Oracle:
                BUDGET = 2
                ACTIONS = [{"name": "ping", "params": {}}]
                def ping(self):
                    return 1
            """,
            {"answer": [7, 7], "tolerance": 0},
        )
        session = self.session("fp")
        session.submit([7, 7])
        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            grade = session.grade()
        self.assertEqual(
            grade["metadata"]["expected_fingerprint"], core.answer_fingerprint([7, 7])
        )


# --------------------------------------------------------------------------- #
# 4. Permissions: private by default, simulation/ deliberately public
# --------------------------------------------------------------------------- #


class ProblemPermissions(HardeningCase):
    def _mode(self, path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)

    def test_oracle_and_golden_become_owner_only(self) -> None:
        directory = write_problem(
            self.root,
            "sealed",
            """
            class Oracle:
                BUDGET = 1
                ACTIONS = [{"name": "ping", "params": {}}]
                def ping(self):
                    return 1
            """,
            {"answer": 1, "tolerance": 0},
        )
        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            core.harden_problem_permissions(directory)
        self.assertEqual(self._mode(directory / "oracle" / "setup.py"), 0o600)
        self.assertEqual(self._mode(directory / "golden" / "expected.json"), 0o600)
        self.assertEqual(self._mode(directory / "oracle"), 0o700)
        # No public subtree, so the problem root stays fully closed.
        self.assertEqual(self._mode(directory), 0o700)

    def test_forward_simulation_inputs_stay_readable(self) -> None:
        """A forward task hands over its inputs — locking them breaks the task."""
        directory = self.root / "forward"
        (directory / "simulation" / "nested").mkdir(parents=True)
        (directory / "golden").mkdir(parents=True)
        (directory / "problem.md").write_text("Run the solver.")
        (directory / "simulation" / "rod.json").write_text('{"length": 10}')
        (directory / "simulation" / "nested" / "mesh.txt").write_text("mesh")
        (directory / "golden" / "expected.json").write_text('{"answer": 3.0}')

        with mock.patch.dict(os.environ, TAIGA_ENV, clear=False):
            core.harden_problem_permissions(directory)

        self.assertEqual(self._mode(directory / "simulation"), 0o755)
        self.assertEqual(self._mode(directory / "simulation" / "rod.json"), 0o644)
        self.assertEqual(self._mode(directory / "simulation" / "nested"), 0o755)
        self.assertEqual(self._mode(directory / "simulation" / "nested" / "mesh.txt"), 0o644)
        # The golden answer beside it stays shut, and the problem root is
        # traversable but not listable.
        self.assertEqual(self._mode(directory / "golden" / "expected.json"), 0o600)
        self.assertEqual(self._mode(directory / "golden"), 0o700)
        self.assertEqual(self._mode(directory), 0o711)

    def test_hardening_is_off_outside_the_image(self) -> None:
        """An authoring checkout must never be mutated by a local run."""
        directory = write_problem(
            self.root,
            "local",
            """
            class Oracle:
                BUDGET = 1
                ACTIONS = [{"name": "ping", "params": {}}]
                def ping(self):
                    return 1
            """,
            {"answer": 1, "tolerance": 0},
        )
        before = self._mode(directory / "oracle" / "setup.py")
        with mock.patch.dict(
            os.environ, {"INVERSE_TASKS_RUNTIME": "build"}, clear=False
        ):
            self.assertEqual(core.harden_problem_permissions(directory), [])
        self.assertEqual(self._mode(directory / "oracle" / "setup.py"), before)


# --------------------------------------------------------------------------- #
# 5. Attempt state must not be solver-forgeable
# --------------------------------------------------------------------------- #


class AttemptStateTrust(HardeningCase):
    """`calls_used` is restored from disk, so a writable snapshot is a budget reset."""

    def setUp(self) -> None:
        super().setUp()
        write_problem(
            self.root,
            "stateful",
            """
            class Oracle:
                BUDGET = 3
                ACTIONS = [{"name": "ping", "params": {}}]
                def ping(self):
                    return 1
            """,
            {"answer": 1, "tolerance": 0},
        )

    def _server(self):
        return server

    def test_group_or_world_accessible_state_is_ignored(self) -> None:
        server = self._server()
        state_file = self.root / "state" / "session.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "problem_id": "stateful",
                    "problem_dir": str((self.root / "stateful").resolve()),
                    "calls_used": 0,
                    "call_log": [],
                    "submitted": True,
                    "submission": 1,
                }
            )
        )
        os.chmod(state_file, 0o644)
        with mock.patch.dict(
            os.environ,
            {
                "INVERSE_TASKS_STATE_PATH": str(state_file),
                "INVERSE_TASKS_PROBLEM_DIRS": str(self.root),
            },
            clear=False,
        ):
            self.assertIsNone(server._restore_session("stateful"))

    def test_owner_only_state_is_accepted(self) -> None:
        server = self._server()
        state_file = self.root / "ok" / "session.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "problem_id": "stateful",
                    "problem_dir": str((self.root / "stateful").resolve()),
                    "calls_used": 2,
                    "call_log": [],
                    "submitted": True,
                    "submission": 1,
                    "setup_calls": 1,
                }
            )
        )
        os.chmod(state_file, 0o600)
        with mock.patch.dict(
            os.environ,
            {
                "INVERSE_TASKS_STATE_PATH": str(state_file),
                "INVERSE_TASKS_PROBLEM_DIRS": str(self.root),
            },
            clear=False,
        ):
            restored = server._restore_session("stateful")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.calls_used, 2)

    def test_state_directory_owned_by_someone_else_is_refused(self) -> None:
        server = self._server()
        foreign = self.root / "foreign"
        foreign.mkdir()
        real_lstat = os.lstat

        def fake_lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if str(path) == str(foreign):
                fields = list(info)
                fields[4] = info.st_uid + 1  # st_uid
                return os.stat_result(tuple(fields))
            return info

        with mock.patch("os.lstat", side_effect=fake_lstat):
            self.assertFalse(server._own_private_dir(foreign))


if __name__ == "__main__":
    unittest.main()
