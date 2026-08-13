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

    async def list_tools(self):
        """Mirrors FastMCP's async tool enumeration, as the harness sees it."""
        return [types.SimpleNamespace(name=name) for name in self.tools]

    def run(self, transport=None):
        self.ran = True


def install_pydantic_stub() -> None:
    """Provide a minimal `pydantic.BaseModel` when the real package is absent.

    `server.py` declares its Grade response model with pydantic. The real
    package is installed in the image but not necessarily in an authoring
    checkout — and without this the whole server suite fails at import and is
    reported as one failed module rather than as missing coverage, which is how
    it went unrun locally. Defer to the real package whenever it is importable.
    """
    if "pydantic" in sys.modules:
        return
    try:
        import pydantic  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    module = types.ModuleType("pydantic")

    class BaseModel:
        """Enough of the interface for a response model: kwargs in, attrs out."""

        def __init__(self, **kwargs):
            for name in getattr(type(self), "__annotations__", {}):
                setattr(self, name, getattr(type(self), name, None))
            for key, value in kwargs.items():
                setattr(self, key, value)

    module.BaseModel = BaseModel
    module.VERSION = "0-stub"
    sys.modules["pydantic"] = module


def install_mcp_stub() -> None:
    install_pydantic_stub()
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
        for name in (
            "setup_problem",
            "grade_problem",
            "describe_oracle",
            "query_oracle",
            "query",
            "submit_answer",
        ):
            self.assertIn(name, self.srv.mcp.tools)

    def test_setup_problem_returns_the_prompt_with_the_tool_guide(self):
        prompt = self.srv.setup_problem("demo")
        self.assertTrue(prompt.startswith("Recover the hidden values."))
        self.assertIn("Using your tools", prompt)
        self.assertEqual(self.srv.state.session.problem.problem_id, "demo")

    def test_tool_guide_documents_the_query_convention_in_generic_mode(self):
        prompt = self.srv.setup_problem("demo")
        self.assertIn('query_oracle(mode="evaluate"', prompt)
        self.assertIn("submit_answer", prompt)
        self.assertIn("Query budget: 3", prompt)

    def test_tool_guide_can_be_suppressed(self):
        prompt = self.srv.setup_problem("demo", extra_fields={"append_tool_guide": False})
        self.assertEqual(prompt, "Recover the hidden values.")

    def test_task_prompt_from_the_form_overrides_problem_md(self):
        prompt = self.srv.setup_problem("demo", extra_fields={"task_prompt": "From the form."})
        self.assertTrue(prompt.startswith("From the form."))
        self.assertNotIn("Recover the hidden values.", prompt)

    def test_a_problem_folder_without_problem_md_is_still_servable(self):
        directory = write_problem(self.root, "noprompt", SIMPLE_ORACLE, {"answer": [5, 2]})
        (directory / "problem.md").unlink()
        prompt = self.srv.setup_problem("noprompt", extra_fields={"task_prompt": "Form text."})
        self.assertTrue(prompt.startswith("Form text."))

    def test_a_problem_with_no_prompt_anywhere_is_an_error(self):
        directory = write_problem(self.root, "silent", SIMPLE_ORACLE, {"answer": [5, 2]})
        (directory / "problem.md").unlink()
        with self.assertRaisesRegex(ValueError, "no task prompt"):
            self.srv.setup_problem("silent")

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

    def test_generic_query_oracle_probes_the_oracle(self):
        self.assertEqual(
            self.srv.mcp.tools["query_oracle"]["fn"]("evaluate", {"x": 1}),
            "7",
        )
        self.assertEqual(self.srv.state.session.calls_used, 1)

    def test_legacy_query_alias_still_probes_the_oracle(self):
        self.assertEqual(self.srv.mcp.tools["query"]["fn"]("evaluate", {"x": 1}), "7")

    def test_generic_query_raises_so_mcp_marks_the_result_as_an_error(self):
        with self.assertRaisesRegex(core.UnknownAction, "Unknown action"):
            self.srv.mcp.tools["query_oracle"]["fn"]("bogus", {})

    def test_budget_exhaustion_is_reported_to_the_model(self):
        query = self.srv.mcp.tools["query_oracle"]["fn"]
        for x in range(3):
            query("evaluate", {"x": x})
        with self.assertRaisesRegex(core.BudgetExceeded, "budget"):
            query("evaluate", {"x": 9})

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

    def test_grade_restores_the_submission_after_an_mcp_restart(self):
        self.srv.mcp.tools["query_oracle"]["fn"]("evaluate", {"x": 0})
        self.srv.submit_answer("[5, 2]")
        self.srv.state.session = None

        grade = self.srv.grade_problem("demo", transcript="after restart")

        self.assertFalse(grade.env_internal_failure)
        self.assertEqual(grade.subscores["correct"], 1.0)
        self.assertEqual(grade.metadata["budget_used"], 1)

    def test_attempt_snapshot_is_root_only_and_omits_the_expected_answer_key(self):
        snapshot = self.srv._state_path()
        payload = json.loads(snapshot.read_text())
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("expected", payload)
        self.assertEqual(payload["problem_id"], "demo")


class TestBoundMode(ServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        write_problem(self.root, "demo", SIMPLE_ORACLE, {"answer": [5, 2], "tolerance": 0})

    def test_declared_actions_become_named_tools(self):
        session = core.load_session("demo", [self.root])
        self.assertTrue(self.srv.register_bound_tools(session))
        self.assertIn("evaluate", self.srv.mcp.tools)
        self.assertIn("help", self.srv.mcp.tools)
        # query stays published alongside the named tools: it is the
        # decorator-registered critical path and a documented fallback.
        self.assertIn("query", self.srv.mcp.tools)

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
        prompt = self.srv.setup_problem("demo")
        self.assertTrue(prompt.startswith("Recover the hidden values."))

    def test_bound_mode_guide_names_the_tools_directly(self):
        self.srv.state.bound_problem_id = "demo"
        prompt = self.srv.setup_problem("demo")
        self.assertIn("`evaluate(x=<integer>)`", prompt)
        self.assertNotIn('query(action="evaluate"', prompt)


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

    def test_a_lone_problem_is_NOT_auto_selected(self):
        # The published tool surface must depend on flags, not on how many
        # problem folders happen to be mounted.
        write_problem(self.root, "only", SIMPLE_ORACLE, {"answer": 1})
        self.assertIsNone(self.srv.resolve_startup_problem(None))

    def test_multiple_problems_stay_generic(self):
        write_problem(self.root, "a", SIMPLE_ORACLE, {"answer": 1})
        write_problem(self.root, "b", SIMPLE_ORACLE, {"answer": 1})
        self.assertIsNone(self.srv.resolve_startup_problem(None))

    def test_default_boot_publishes_query_only(self):
        write_problem(self.root, "only", SIMPLE_ORACLE, {"answer": [5, 2]})
        self.srv.main([])
        self.assertTrue(self.srv.mcp.ran)
        self.assertIn("query", self.srv.mcp.tools)
        self.assertNotIn("evaluate", self.srv.mcp.tools)
        self.assertIsNone(self.srv.state.bound_problem_id)

    def test_named_tools_requires_a_problem_id(self):
        write_problem(self.root, "only", SIMPLE_ORACLE, {"answer": [5, 2]})
        self.srv.main(["--named-tools"])
        self.assertTrue(self.srv.mcp.ran, "the container must still boot")
        self.assertIn("query", self.srv.mcp.tools)
        self.assertNotIn("evaluate", self.srv.mcp.tools)

    def test_named_tools_publishes_actions_when_given_a_problem_id(self):
        write_problem(self.root, "only", SIMPLE_ORACLE, {"answer": [5, 2]})
        self.srv.main(["--named-tools", "--problem-id", "only"])
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
        self.srv.main(["--named-tools", "--problem-id", "broken"])
        self.assertTrue(self.srv.mcp.ran, "the container must still boot")
        self.assertIn("query", self.srv.mcp.tools)
        self.assertIsNone(self.srv.state.bound_problem_id)


class TestSelfTest(ServerTestCase):
    """The check the Docker build runs, where the real `mcp` package is installed."""

    def test_selftest_passes_for_a_well_formed_problem(self):
        write_problem(self.root, "demo", SIMPLE_ORACLE, {"answer": [5, 2], "tolerance": 0})
        self.assertEqual(self.srv.selftest("demo"), 0)

    def test_selftest_reports_no_problems(self):
        self.assertEqual(self.srv.selftest(), 1)

    def test_selftest_fails_when_the_golden_answer_does_not_grade(self):
        # A golden answer the engine can never match must not pass the build gate.
        write_problem(self.root, "broken", SIMPLE_ORACLE, {"answer": [5, 2], "tolerance": 0})
        original = core.compare_answers
        core.compare_answers = lambda submission, golden: {
            "score": 0.0, "correct": False, "matches": 0, "total": 2,
            "details": [], "scoring": "binary", "tolerance": 0,
        }
        self.addCleanup(setattr, core, "compare_answers", original)
        self.assertEqual(self.srv.selftest("broken"), 1)

    def test_selftest_enumerates_the_required_tools(self):
        write_problem(self.root, "demo", SIMPLE_ORACLE, {"answer": [5, 2], "tolerance": 0})
        names = self.srv.published_tool_names()
        for required in (
            "setup_problem",
            "grade_problem",
            "query_oracle",
            "query",
            "submit_answer",
            "describe_oracle",
        ):
            self.assertIn(required, names)


class TestStdoutIsProtected(ServerTestCase):
    """stdout is the MCP transport; expert oracle code must never reach it."""

    NOISY_ORACLE = """
        import sys
        print("module-level print")

        class Oracle:
            BUDGET = 3
            ACTIONS = [{"name": "probe", "params": {"x": {"type": "integer", "required": True}}}]
            def __init__(self):
                print("constructor print")
            def probe(self, x):
                print("probe print")
                sys.stdout.write("raw stdout write\\n")
                return x * 2
    """

    def setUp(self) -> None:
        super().setUp()
        write_problem(self.root, "noisy", self.NOISY_ORACLE, {"answer": [1], "tolerance": 0})

    def test_oracle_prints_do_not_reach_stdout(self):
        import contextlib
        import io

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.srv.setup_problem("noisy")
            result = self.srv.query("probe", {"x": 21})
        self.assertEqual(captured.getvalue(), "", "oracle output leaked into the MCP transport")
        self.assertEqual(result, "42", "the observation itself must still be returned")

    def test_custom_grader_prints_do_not_reach_stdout(self):
        import contextlib
        import io

        write_problem(
            self.root,
            "noisygrader",
            SIMPLE_ORACLE,
            {"answer": [5, 2], "tolerance": 0},
            grader_src='def grade(**kwargs):\n    print("grader print")\n    return 1.0\n',
        )
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.srv.setup_problem("noisygrader")
            self.srv.submit_answer("[5, 2]")
            grade = self.srv.grade_problem("noisygrader")
        self.assertEqual(captured.getvalue(), "")
        self.assertEqual(grade.subscores["correct"], 1.0)


class TestGradeBounds(ServerTestCase):
    """Taiga type-errors on a weighted grade above 1.0, which fails the episode."""

    ORACLE = SIMPLE_ORACLE

    def test_overweighted_custom_grader_is_normalised(self):
        write_problem(
            self.root,
            "heavy",
            self.ORACLE,
            {"answer": [5, 2], "tolerance": 0},
            grader_src=(
                "def grade(**kwargs):\n"
                "    return {\n"
                '        "subscores": {"a": 1.0, "b": 1.0},\n'
                '        "weights": {"a": 1.0, "b": 1.0},\n'
                "    }\n"
            ),
        )
        self.srv.setup_problem("heavy")
        self.srv.submit_answer("[5, 2]")
        grade = self.srv.grade_problem("heavy")
        weighted = sum(grade.subscores[k] * w for k, w in grade.weights.items())
        self.assertLessEqual(weighted, 1.0)
        self.assertIn("weights_normalised", grade.metadata)

    def test_wellformed_weights_are_left_alone(self):
        write_problem(
            self.root,
            "fine",
            self.ORACLE,
            {"answer": [5, 2], "tolerance": 0},
            grader_src=(
                "def grade(**kwargs):\n"
                "    return {\n"
                '        "subscores": {"a": 1.0, "b": 0.5},\n'
                '        "weights": {"a": 0.5, "b": 0.5},\n'
                "    }\n"
            ),
        )
        self.srv.setup_problem("fine")
        self.srv.submit_answer("[5, 2]")
        grade = self.srv.grade_problem("fine")
        self.assertEqual(grade.weights, {"a": 0.5, "b": 0.5})
        self.assertNotIn("weights_normalised", grade.metadata)

    def test_grade_model_accepts_every_spec_field(self):
        # Matches the Grade model in the Taiga wiki's Required Hooks section.
        grade = self.srv.Grade(
            subscores={"correct": 1.0},
            weights={"correct": 1.0},
            metadata={"k": "v"},
            env_internal_failure=False,
            env_internal_failure_logs=["log"],
            penalties={"p": 0.1},
            allow_unbounded=False,
        )
        self.assertEqual(grade.subscores["correct"], 1.0)
        self.assertFalse(grade.allow_unbounded)


class TestShippedSampleThroughTheServer(unittest.TestCase):
    """The real problem in this repo, driven exactly as Taiga would drive it."""

    def setUp(self) -> None:
        importlib.reload(server)
        self.srv = server

    def test_bound_mode_publishes_the_tools_the_prompt_names(self):
        self.srv.main(["--named-tools", "--problem-id", "modular-black-box"])
        self.assertIn("evaluate", self.srv.mcp.tools)
        self.assertIn("help", self.srv.mcp.tools)
        self.assertNotIn("sample", self.srv.mcp.tools)

    def test_intended_path_through_the_published_tools(self):
        self.srv.main(["--named-tools", "--problem-id", "modular-black-box"])
        self.srv.setup_problem("modular-black-box")
        evaluate = self.srv.mcp.tools["evaluate"]["fn"]
        b = int(evaluate(0))
        y1 = int(evaluate(1))
        self.srv.submit_answer(json.dumps([(y1 - b) % 97, b]))
        grade = self.srv.grade_problem("modular-black-box")
        self.assertEqual(grade.subscores["correct"], 1.0)

    def test_near_miss_path_through_the_published_tools(self):
        self.srv.main(["--named-tools", "--problem-id", "modular-black-box"])
        self.srv.setup_problem("modular-black-box")
        evaluate = self.srv.mcp.tools["evaluate"]["fn"]
        y10, y30 = int(evaluate(10)), int(evaluate(30))
        a = round((y30 - y10) / 20)
        self.srv.submit_answer(json.dumps([a, y10 - a * 10]))
        self.assertEqual(
            self.srv.grade_problem("modular-black-box").subscores["correct"], 0.0
        )

    def test_help_is_free(self):
        self.srv.main(["--named-tools", "--problem-id", "modular-black-box"])
        self.srv.setup_problem("modular-black-box")
        self.srv.mcp.tools["help"]["fn"]("anything")
        self.assertEqual(self.srv.state.session.calls_used, 0)

    def test_grade_metadata_is_json_serialisable(self):
        self.srv.main(["--named-tools", "--problem-id", "modular-black-box"])
        self.srv.setup_problem("modular-black-box")
        self.srv.mcp.tools["evaluate"]["fn"](0)
        self.srv.submit_answer("[23, 58]")
        grade = self.srv.grade_problem("modular-black-box")
        json.dumps(grade.metadata)  # Taiga has to serialise this


if __name__ == "__main__":
    unittest.main(verbosity=2)
