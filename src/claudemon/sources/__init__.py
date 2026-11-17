"""The data layer. SOURCES lists the data sources the Store keeps beside the transcripts, in order.

Each entry is (name, factory, stage). Store() builds factory() as store.<name>, so a page reads it
through a Store method, and Store.refresh() calls its refresh() every tick: stage "first" before the
live registry is read, "last" after the transcripts. A failing refresh is swallowed, so one source
can never take the store down. Adding a data source is one module plus one SOURCES line.
"""

from claudemon.sources.limits import LimitLog
from claudemon.sources.procs import Processes

SOURCES = [
    ("procs", Processes, "first"),    # the registry's liveness check reads the process table
    ("limits", LimitLog, "last"),     # the tap's limits log
]
