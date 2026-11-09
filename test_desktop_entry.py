import ast
from pathlib import Path
import unittest
from unittest.mock import patch


ENTRY = Path(__file__).with_name("JuiceGuesserMain.py")


class DesktopEntryTests(unittest.TestCase):
    def test_entry_contains_only_runtime_dispatch(self):
        source = ENTRY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        imported = {alias.name for node in imports for alias in node.names}

        self.assertNotIn("tkinter", imported)
        self.assertNotIn("pygame", imported)
        self.assertNotIn("Spotify local Files", source)
        self.assertFalse(any(isinstance(node, ast.ClassDef) for node in tree.body))

    def test_explicit_beta_diagnostic_dispatches_without_test_environment(self):
        import JuiceGuesserMain

        with patch.object(JuiceGuesserMain.sys, "argv", [str(ENTRY), "--beta-update-smoke-test", "context.json"]), \
             patch.dict("os.environ", {}, clear=True), \
             patch("beta_update_smoke.run", return_value=7) as run:
            self.assertEqual(JuiceGuesserMain.main(), 7)
        run.assert_called_once_with("context.json")

    def test_post_update_sets_health_handoff_then_starts_app(self):
        import JuiceGuesserMain

        with patch.object(JuiceGuesserMain.sys, "argv", [str(ENTRY), "--post-update", "job", "token"]), \
             patch("update_health.set_handoff") as set_handoff, \
             patch("web_app.main") as run_app:
            self.assertEqual(JuiceGuesserMain.main(), 0)
        set_handoff.assert_called_once_with("job", "token")
        run_app.assert_called_once_with()

    def test_beta_environment_alone_does_not_switch_startup_mode(self):
        import JuiceGuesserMain

        with patch.object(JuiceGuesserMain.sys, "argv", [str(ENTRY)]), \
             patch.dict("os.environ", {"GRAILD_BETA_TEST_CONTEXT": "context.json"}), \
             patch("web_app.main") as run_app:
            self.assertEqual(JuiceGuesserMain.main(), 0)
        run_app.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
