"""Tools for the Noy et al. (2025) mirror-game tracking study.

People followed a dot that moved left and right on a tablet. The dot followed
a sine wave whose frequency changed in blocks from 0.25 to 0.5625 Hz. The pen
x position was recorded for people with Parkinson's disease, older controls,
and young controls.
"""

from ml.study.load import GROUP_NAMES, Study, load_study

__all__ = ["GROUP_NAMES", "Study", "load_study"]
