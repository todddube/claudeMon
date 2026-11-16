#!/usr/bin/env python3
"""claudeMon from a clone, with nothing installed: the code lives in src/claudemon/.

Run it (./claudemon.py, a symlink to it, python3 claudemon.py) and it starts claudemon.
Imported as `claudemon` (from this folder, or by a tool that puts it on sys.path), it replaces
itself in sys.modules with the real package, so there is only ever one copy of each module.
"""

import os
import sys

_WRAPPER = os.path.realpath(__file__)      # a symlink's own folder has no src/
_SRC = os.path.join(os.path.dirname(_WRAPPER), "src")
if sys.path[:1] != [_SRC]:
    sys.path.insert(0, _SRC)

if __name__ == "__main__":
    from claudemon.core import runtime
    from claudemon.cli import main
    runtime.WRAPPER = _WRAPPER           # --window starts this file again
    main()
elif __name__ == "claudemon":
    del sys.modules[__name__]
    import importlib
    importlib.import_module(__name__)    # the importer gets whatever sys.modules holds: the package
