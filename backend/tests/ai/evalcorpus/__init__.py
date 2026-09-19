"""The synthetic world the AskService benchmark is graded against.

`shape.py` holds the facts — every field a question can be asked about, written
by hand. `ids.py` mints stable identifiers for them. Prose (subjects, bodies,
names) is generated separately and frozen; nothing in here depends on it, so the
grading never moves when the wording does.
"""
