"""End-of-visit numbers for the three lobby games.

Frames stay in memory until `finish_visit` returns. The returned document has
the dashboard figures and the model scores. It does not contain the frames.
"""

from ml.visit_report.report import finish_visit

__all__ = ["finish_visit"]
