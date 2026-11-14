"""One generator per platform. Each models that platform's REAL export structure.

The rule from buildNOTES §6 applies here as much as anywhere: a generator written
before the real payload is a guess. `telegram.py` is written after two real
exports were read; the others stay TODO until their real file exists.

A generator's job is structure, not content. Fields, shapes, nulls, odd cases —
those must match the platform. Text should be obviously fake so nobody mistakes
generated data for real.
"""
