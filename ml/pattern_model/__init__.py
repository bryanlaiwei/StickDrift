"""Per-hand DualSense pattern model.

The slow path of each stick is removed first. One shared network then scores
the leftover of whichever hand is moving: the shake, how late, slow, or
shrinking the reach was, and how far the stick missed its target. Parkinson
is the impairment shared by both hands. Stroke is the gap between them.
Essential tremor is the shake.

Scores come back as parkinson, stroke, and essential_tremor, each from 0 to 100. They are pattern resemblance, not disease probabilities,
and they do not sum to 100.
"""

from ml.pattern_model.labels import load_examples, load_training_examples
from ml.pattern_model.predict import score
from ml.pattern_model.recording import Example, Recording
from ml.pattern_model.score import fuse
from ml.pattern_model.train import fit

__all__ = ["Example", "Recording", "fit", "fuse", "load_examples", "load_training_examples", "score"]
