"""Everything that runs in the root uv environment (Python 3.14, torch).

pattern_model/  the movement pattern model: recordings, training, scoring
visit_report/   end-of-visit numbers and pattern scores for one lobby visit
hand_replay/    reconstructed-hands GIFs from recordings and lobby visits
study/          figures from an external recording study
runs/           trained checkpoints (only pattern_model/model.pt is committed)

Run modules from the repository root, e.g. `uv run python -m ml.pattern_model.train`.
"""
