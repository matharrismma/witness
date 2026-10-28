"""canon — the Bible as a hash table, a scripture verifier for Concordance, and a small cite-only model.

Nothing is generated: found, verified, cited, sealed. The text lives in the table (table.py), never in a
model's weights; the verifier (verifier.py) checks quotes by hash; the generator (synth.py) makes training
trajectories and drops any example whose quote fails; the eval (evaluate.py) reports counterexample rates
with Bayesian posteriors; train.py fine-tunes a small (default 1.58-bit) model to look up and cite.
"""
__version__ = "0.1.0"
