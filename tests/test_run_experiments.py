"""
Tests for scripts/run_experiments.py. Run all tests with:

    .venv/bin/python -m unittest discover -s tests -v

1. Without --controllers it plans and starts exactly the runs it did before
   "proactive_nopred" was added: reactive, proactive, reactive, ...
2. proactive_nopred runs proactive.py --predict-ahead 0 under its own name,
   so its files and runs.csv rows stay apart from the normal proactive runs.
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import run_experiments as runner  # noqa: E402  (scripts/run_experiments.py)


class DefaultUnchanged(unittest.TestCase):

    def test_plan(self):
        # The plan as the runner made it before: every repeat, reactive then proactive.
        before = [(controller, repeat) for repeat in range(1, 4)
                  for controller in ["reactive", "proactive"]]
        self.assertEqual(runner.make_plan(runner.CONTROLLERS, 3), before)

    def test_commands_and_log_files(self):
        for name in ("reactive", "proactive"):
            with self.subTest(controller=name):
                self.assertEqual(runner.controller_command(name),
                                 [sys.executable, "-u", os.path.join(ROOT, "controller", f"{name}.py")])
                self.assertEqual(runner.controller_log(name),
                                 os.path.join(ROOT, "data", f"{name}_log.csv"))


class NoPredictionVariant(unittest.TestCase):

    def test_command(self):
        self.assertEqual(runner.controller_command("proactive_nopred"),
                         [sys.executable, "-u", os.path.join(ROOT, "controller", "proactive.py"),
                          "--predict-ahead", "0"])

    def test_writes_the_proactive_log_file(self):
        # The runner moves it to <out-dir>/proactive_nopred_<n>.csv after each run.
        self.assertEqual(runner.controller_log("proactive_nopred"),
                         os.path.join(ROOT, "data", "proactive_log.csv"))

    def test_own_run_numbers(self):
        plan = runner.make_plan(["proactive_nopred", "reactive", "proactive_nopred",
                                 "proactive", "proactive_nopred"], 1)
        self.assertEqual(plan, [("proactive_nopred", 1), ("reactive", 1), ("proactive_nopred", 2),
                                ("proactive", 1), ("proactive_nopred", 3)])


if __name__ == "__main__":
    unittest.main()
