"""Tests for the MCP server layer.

The `mcp` package isn't needed to exercise this logic, so a minimal FastMCP
stand-in is installed in sys.modules before importing `server`. That keeps the
suite runnable anywhere while still covering the parts most likely to break:
which tools get published in which mode, and the setup -> probe -> submit ->
grade round trip Taiga drives.
"""
from __future__ import annotations

import importlib
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_core import write_problem  # noqa: E402


class FakeFastMCP:
    """Records what the real FastMCP would publish to the harness."""

    def __init__(self, name: str):
        self.name = name
        self.tools: dict[str, dict] = {}
        self.ran = False

    def tool(self, *args, **kwargs):
        def decorate(fn):
            self.tools[kwargs.get("name", fn.__name__)] = {
                "fn": fn,
                "description": kwargs.get("description") or (fn.__doc__ or ""),
            }
            return fn  # keep the module-level name callable

        return decorate

    def add_tool(self, fn, name=None, description=None, **kwargs):
        resolved = name or getattr(fn, "__name__", None)
        if resolved is None:
            raise ValueError("tool needs a name")
        self.tools[resolved] = {"fn": fn, "description": description or (fn.__doc__ or "")}

    def run(self, transport=None):
        self.ran = True


def install_mcp_stub() -> None:
    if "mcp.server.fastmcp" in sys.modules:
        return
    pkg = types.ModuleType("mcp")
    server_pkg = types.ModuleType("mcp.server")
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    fastmcp.FastMCP = FakeFastMCP
    server_pkg.fastmcp = fastmcp
    pkg.server = server_pkg
    sys.modules.setdefault("mcp", pkg)
    sys.modules.setdefault("mcp.server", server_pkg)
    sys.modules.setdefault("mcp.server.fastmcp", fastmcp)


install_mcp_stub()

import core  # noqa: E402
import server  # noqa: E402


class ServerTestCase(unittest.TestCase):
    """Each test gets a pristine server module and an isolated problems dir."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="inverse-server-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        importlib.reload(server)
        self.srv = server
        self._patch_roots([self.root])

    def _patch_roots(self, roots) -> None:
        """Point core's default problem search at this test's temp dir."""
        original = core.problem_roots
        core.problem_roots = lambda explicit=None: [
            Path(p) for p in (explicit if explicit is not None else roots)
        ]
        self.addCleanup(setattr, core, "problem_roots", original)


SIMPLE_ORACLE = """
    class Oracle:
        BUDGET = 3
        ACTIONS = [
            {"name": "evaluate",
             "description": "Return the output for x.",
             "params": {"x": {"type": "integer", "required": True}}},
            {"name": "help",
             "description": "A general hint.",
             "params": {"question": {"type": "string", "default": ""}},
             "costs_budget": False},
        ]
        def evaluate(self, x):
            return (5 * x + 2) % 11
        def help(self, question=""):
            return "no comment"
"""


class TestScaffoldHooks(ServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        write_problem(self.root, "demo", SIMPLE_ORACLE, {"answer": [5, 2], "tolerance": 0})

    def test_scaffold_hooks_are_published(self):
        for name in ("setup_problem", "grade_problem", "describe_oracle", "submit_answer"):
            self.assertIn(name, self.srv.mcp.tools)

    def test_setup_problem_returns_the_prompt(self):
        prompt = self.srv.setup_problem("demo")
        self.assertEqual(prompt, "Recover the hidden values.")
        self.assertEqual(self.srv.state.session.problem.problem_id, "demo")

    def test_setup_problem_rejects_an_unknown_id(self):
        with self.assertRaises(core.ProblemNotFound):
            self.srv.setup_problem("nope")

    def test_setup_problem_starts_a_fresh_attempt(self):
        self.srv.setup_problem("demo")
        self.srv.state.session.query("evaluate", {"x": 1})
        self.assertEqual(self.srv.state.session.calls_used, 1)
        self.srv.setup_problem("demo")
        self.assertEqual(self.srv.state.session.calls_used, 0)

    def test_extra_fields_can_append_a_prompt_suffix(self):
        prompt = self.srv.setup_problem("demo", extra_fields={"prompt_suffix": "Be brief."})
        self.assertTrue(prompt.endswith("Be brief."))

    def test_grade_before_setup_is_an_env_internal_failure(self):
        grade = self.srv.grade_problem("demo")
        self.assertTrue(grade.env_internal_failure)
        self.assertEqual(grade.subscores["correct"], 0.0)

    def test_grade_for_a_different_problem_is_an_env_internal_failure(self):
        write_problem(self.root, "other", SIMPLE_ORACLE, {"answer": [5, 2]})
        self.srv.setup_problem("demo")
        grade = self.srv.grade_problem("other")
        self.assertTrue(grade.env_internal_failure)

    def test_list_problems_reports_what_is_servable(self):
        write_problem(self.root, "second", SIMPLE_ORACLE, {"answer": [5, 2]})
        self.assertEqual(json.loads(self.srv.list_problems()), ["demo", "second"])


class TestModelFacingFlow(ServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        write_problem(
            self.root,
            "demo",
            SIMPLE_ORACLE,
            {"answer": [5, 2], "tolerance": 0, "keys": ["a", "b"]},
        )
        self.srv.register_generic_tools()
        self.srv.setup_problem("demo")

    def test_tools_before_setup_explain_themselves(self):
        importlib.reload(self.srv)
        self._patch_roots([self.root])
        with self.assertRaisesRegex(RuntimeError, "setup_problem"):
            self.srv.describe_oracle()

    def test_describe_oracle_lists_actions_and_budget(self):
        described = json.loads(self.srv.describe_oracle())
        self.assertEqual([a["name"] for a in described["actions"]], ["evaluate", "help"])
        self.assertEqual(described["budget_total"], 3)
        self.assertEqual(described["budget_remaining"], 3)

    def test_describe_oracle_does_not_reveal_the_answer(self):
        # The golden answer here is [5, 2]; the shape may state length/types but
        # must not carry the values themselves.
        shape = json.loads(self.srv.describe_oracle())["answer_shape"]
        self.assertEqual(shape["type"], "array")
        self.assertEqual(shape["length"], 2)
        self.assertNotIn("answer", shape)
        self.assertNotIn(5, json.loads(json.dumps(list(shape.values()))))

    def test_generic_query_probes_the_oracle(self):
        self.assertEqual(self.srv.mcp.tools["query"]["fn"]("evaluate", {"x": 1}), "7")
        self.assertEqual(self.srv.state.session.calls_used, 1)

    def test_generic_query_reports_errors_as_text(self):
        result = self.srv.mcp.tools["query"]["fn"]("bogus", {})
        self.assertIn("Unknown action", result)

    def test_budget_exhaustion_is_reported_to_the_model(self):
        query = self.srv.mcp.tools["query"]["fn"]
        for x in range(3):
            query("evaluate", {"x": x})
        self.assertIn("budget", query("evaluate", {"x": 9}).lower())

    def test_happy_path_scores_one(self):
        self.srv.mcp.tools["query"]["fn"]("evaluate", {"x": 0})
        self.srv.submit_answer("[5, 2]")
        grade = self.srv.grade_problem("demo", transcript="...")
        self.assertEqual(grade.subscores["correct"], 1.0)
        self.assertEqual(grade.metadata["budget_used"], 1)

    def test_wrong_answer_scores_zero(self):
        self.srv.submit_answer("[1, 1]")
        self.assertEqual(self.srv.grade_problem("demo").subscores["correct"], 0.0)

    def test_submit_accepts_a_keyed_object(self):
        self.srv.submit_answer('{"a": 5, "b": 2}')
        self.assertEqual(self.srv.grade_problem("demo").subscores["correct"], 1.0)

    def test_submit_warns_on_a_shape_mismatch(self):
        message = self.srv.submit_answer("[5]")
        self.assertIn("Warning", message)
        self.assertIn("2 element", message)

    def test_submit_warning_does_not_reveal_the_answer(self):
        # Distinctive golden values, so their absence from the feedback is meaningful.
        write_problem(self.root, "distinct", SIMPLE_ORACLE, {"answer": [7331, 8942]})
        self.srv.setup_problem("distinct")
        message = self.srv.submit_answer("[1]")
        self.assertIn("Warning", message)
        self.assertNotIn("7331", message)
        self.assertNotIn("8942", message)

    def test_resubmission_wins(self):
        self.srv.submit_answer("[9, 9]")
        self.srv.submit_answer("[5, 2]")
        self.assertEqual(self.srv.grade_problem("demo").subscores["correct"], 1.0)

    def test_unparseable_answer_is_kept_verbatim_and_warned_about(self):
        message = self.srv.submit_answer("a is 5 and b is 2")
        self.assertIn("Warning", message)
        self.assertEqual(self.srv.grade_problem("demo").subscores["correct"], 0.0)


class TestBoundMode(ServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        write_problem(self.root, "demo", SIMPLE_ORACLE, {"answer": [5, 2], "tolerance": 0})

    def test_declared_actions_become_named_tools(self):
        session = core.load_session("demo", [self.root])
        self.assertTrue(self.srv.register_bound_tools(session))
        self.assertIn("evaluate", self.srv.mcp.tools)
        self.assertIn("help", self.srv.mcp.tools)
        self.assertNotIn("query", self.srv.mcp.tools)

    def test_named_tool_calls_through_to_the_oracle(self):
        session = core.load_session("demo", [self.root])
        self.srv.register_bound_tools(session)
        self.srv.state.session = session
        self.assertEqual(self.srv.mcp.tools["evaluate"]["fn"](1), "7")
        self.assertEqual(session.calls_used, 1)

    def test_named_tool_description_mentions_budget_cost(self):
        session = core.load_session("demo", [self.root])
        self.srv.register_bound_tools(session)
        self.assertIn("spends one unit", self.srv.mcp.tools["evaluate"]["description"])
        self.assertIn("does not spend", self.srv.mcp.tools["help"]["description"])

    def test_undeclared_oracle_cannot_be_bound(self):
        write_problem(
            self.root,
            "undeclared",
            "class Oracle:\n    def query(self, mode, **kw):\n        return 1\n",
            {"answer": 1},
        )
        session = core.load_session("undeclared", [self.root])
        self.assertFalse(self.srv.register_bound_tools(session))

    def test_registration_failure_falls_back_to_generic_mode(self):
        session = core.load_session("demo", [self.root])

        def explode(*args, **kwargs):
            raise RuntimeError("this FastMCP version disagrees")

        self.srv.mcp.add_tool = explode
        self.assertFalse(self.srv.register_bound_tools(session))

    def test_bound_container_rejects_a_mismatched_setup_call(self):
        write_problem(self.root, "other", SIMPLE_ORACLE, {"answer": [5, 2]})
        self.srv.state.bound_problem_id = "demo"
        with self.assertRaisesRegex(ValueError, "bound to problem"):
            self.srv.setup_problem("other")

    def test_bound_container_accepts_the_matching_setup_call(self):
        self.srv.state.bound_problem_id = "demo"
        self.assertEqual(self.srv.setup_problem("demo"), "Recover the hidden values.")


class TestStartupResolution(ServerTestCase):
    def test_explicit_flag_wins(self):
        write_problem(self.root, "a", SIMPLE_ORACLE, {"answer": 1})
        write_problem(self.root, "b", SIMPLE_ORACLE, {"answer": 1})
        self.assertEqual(self.srv.resolve_startup_problem("b"), "b")

    def test_env_var_is_used_when_no_flag(self):
        write_problem(self.root, "a", SIMPLE_ORACLE, {"answer": 1})
        write_problem(self.root, "b", SIMPLE_ORACLE, {"answer": 1})
        import os

        os.environ["PROBLEM_ID"] = "a"
        self.addCleanup(os.environ.pop, "PROBLEM_ID", None)
        self.assertEqual(self.srv.resolve_startup_problem(None), "a")

    def test_a_lone_problem_is_auto_selected(self):
        write_problem(self.root, "only", SIMPLE_ORACLE, {"answer": 1})
        self.assertEqual(self.srv.resolve_startup_problem(None), "only")

    def test_multiple_problems_stay_generic(self):
        write_problem(self.root, "a", SIMPLE_ORACLE, {"answer": 1})
        write_problem(self.root, "b", SIMPLE_ORACLE, {"answer": 1})
        self.assertIsNone(self.srv.resolve_startup_problem(None))

    def test_main_boots_in_bound_mode_for_a_lone_problem(self):
        write_problem(self.root, "only", SIMPLE_ORACLE, {"answer": [5, 2]})
        self.srv.main([])
        self.assertTrue(self.srv.mcp.ran)
        self.assertIn("evaluate", self.srv.mcp.tools)
        self.assertEqual(self.srv.state.bound_problem_id, "only")

    def test_main_boots_in_generic_mode_for_several_problems(self):
        write_problem(self.root, "a", SIMPLE_ORACLE, {"answer": [5, 2]})
        write_problem(self.root, "b", SIMPLE_ORACLE, {"answer": [5, 2]})
        self.srv.main([])
        self.assertTrue(self.srv.mcp.ran)
        self.assertIn("query", self.srv.mcp.tools)
        self.assertNotIn("evaluate", self.srv.mcp.tools)
        self.assertIsNone(self.srv.state.bound_problem_id)

    def test_main_survives_an_unloadable_bound_problem(self):
        write_problem(self.root, "broken", "class NotAnOracle:\n    pass\n", {"answer": 1})
        self.srv.main([])
        self.assertTrue(self.srv.mcp.ran, "the container must still boot")
        self.assertIn("query", self.srv.mcp.tools)


class TestShippedSampleThroughTheServer(unittest.TestCase):
    """The real problem in this repo, driven exactly as Taiga would drive it."""

    def setUp(self) -> None:
        importlib.reload(server)
        self.srv = server

    def test_bound_mode_publishes_the_tools_the_prompt_names(self):
        self.srv.main(["--problem-id", "modular-black-box"])
        self.assertIn("evaluate", self.srv.mcp.tools)
        self.assertIn("help", self.srv.mcp.tools)
        self.assertNotIn("sample", self.srv.mcp.tools)

    def test_intended_path_through_the_published_tools(self):
        self.srv.main(["--problem-id", "modular-black-box"])
        self.srv.setup_problem("modular-black-box")
        evaluate = self.srv.mcp.tools["evaluate"]["fn"]
        b = int(evaluate(0))
        y1 = int(evaluate(1))
        self.srv.submit_answer(json.dumps([(y1 - b) % 97, b]))
        grade = self.srv.grade_problem("modular-black-box")
        self.assertEqual(grade.subscores["correct"], 1.0)

    def test_near_miss_path_through_the_published_tools(self):
        self.srv.main(["--problem-id", "modular-black-box"])
        self.srv.setup_problem("modular-black-box")
        evaluate = self.srv.mcp.tools["evaluate"]["fn"]
        y10, y30 = int(evaluate(10)), int(evaluate(30))
        a = round((y30 - y10) / 20)
        self.srv.submit_answer(json.dumps([a, y10 - a * 10]))
        self.assertEqual(
            self.srv.grade_problem("modular-black-box").subscores["correct"], 0.0
        )

    def test_help_is_free(self):
        self.srv.main(["--problem-id", "modular-black-box"])
        self.srv.setup_problem("modular-black-box")
        self.srv.mcp.tools["help"]["fn"]("anything")
        self.assertEqual(self.srv.state.session.calls_used, 0)

    def test_grade_metadata_is_json_serialisable(self):
        self.srv.main(["--problem-id", "modular-black-box"])
        self.srv.setup_problem("modular-black-box")
        self.srv.mcp.tools["evaluate"]["fn"](0)
        self.srv.submit_answer("[23, 58]")
        grade = self.srv.grade_problem("modular-black-box")
        json.dumps(grade.metadata)  # Taiga has to serialise this


if __name__ == "__main__":
    unittest.main(verbosity=2)
