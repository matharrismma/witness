"""witness — the witness / record / experience layer of Narrow Highway (V3).

This package is an APPLICATION that sits on top of the Narrow Highway core engine. It holds
surfaces and orchestration (the Scribe first; the witness record, community and coach to follow)
and calls the core over HTTP for every verification and every seal. It never imports the core,
holds no verifier and no corpus of its own: one engine, one corpus, two surfaces.
"""
__version__ = "0.1.0"
