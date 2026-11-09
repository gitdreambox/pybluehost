"""PyBlueHostTestCase — TestCaseLT1 that owns the pts-tester lifecycle.

Mirrors bluez's ``BTestCase``: every test case first starts the IUT subprocess
(``pts-tester --connect``), waits for its Core READY event, then runs the
profile pre_conditions; on teardown it cleans the autopts Stack model and stops
the subprocess.

autopts is imported at module load (this base class is only ever instantiated
inside a running autoptsclient session), so importing this module requires
autoptsclient to be installed — PyBlueHost CI stubs it.
"""
from __future__ import annotations

from autopts.ptsprojects.stack import get_stack
from autopts.ptsprojects.testcase import TestCaseLT1, TestFunc, TestFuncCleanUp

from auto_pts_project.pybluehost_iut.iutctl import get_iut


class PyBlueHostTestCase(TestCaseLT1):
    """A PyBlueHost test case (single Lower Tester)."""

    def __init__(self, *args, **kwargs):
        """Refer to TestCase.__init__ for parameters and their documentation."""
        super().__init__(*args, ptsproject_name="pybluehost_iut", **kwargs)

        self.stack = get_stack()
        self.iutctl = get_iut()

        # First command: start the IUT (spawn pts-tester, accept its dial-out).
        self.cmds.insert(0, TestFunc(self.iutctl.start, self))
        # Then block for the Core IUT_READY event before any BTP command.
        self.cmds.insert(1, TestFunc(self.iutctl.wait_iut_ready_event))

        self.cmds.append(TestFuncCleanUp(self.stack.cleanup))
        # Last command: stop the IUT subprocess.
        self.cmds.append(TestFuncCleanUp(self.iutctl.stop))
