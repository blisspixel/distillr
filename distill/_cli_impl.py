"""CLI implementation — backward-compatible re-export shim.

All business logic now lives in ``distill/commands/_logic.py``.
This module aliases itself to that module via ``sys.modules`` so that:

1. Existing tests that patch ``distill._cli_impl.get_config`` etc. keep working
   (the patch targets the same module object that command functions use).
2. The ``distill/cli.py`` wildcard import continues to function.
3. Any third-party code importing from ``distill._cli_impl`` is unaffected.

After this shim executes, ``distill._cli_impl`` and ``distill.commands._logic``
refer to the **same** module object in ``sys.modules``.
"""

import sys

import distill.commands._logic as _logic

# Replace this module in sys.modules with the canonical _logic module.
# This ensures that patching ``distill._cli_impl.X`` patches the same
# object that command functions reference, preserving test compatibility.
sys.modules[__name__] = _logic
