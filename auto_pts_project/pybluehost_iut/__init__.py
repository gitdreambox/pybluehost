"""PyBlueHost auto-pts project module.

When autoptsclient is configured for `--project pybluehost_iut`, it imports
this package and calls into ``iutctl`` / ``pics`` / ``ixit`` / ``wid``. The
``_iut`` suffix disambiguates this plugin folder from the protocol-stack
package (``pybluehost``) on sys.path — both directories sit on disk under the
same repo, and a bare ``import pybluehost`` from autoptsclient must always
resolve to the stack, not this plugin.

See README.md for the operator runbook (added in P.9 Task 5).
"""
PROJECT_NAME = "pybluehost_iut"
