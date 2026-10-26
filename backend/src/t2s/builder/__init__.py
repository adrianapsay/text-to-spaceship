"""CubeSat Builder (V3): from a mission idea to an engineering-informed CubeSat design.

* model.py — the design record: answers, requirements (each with where its value came from), selections, history.
* questions.py — the adaptive questionnaire: which question applies next, "I don't know" with explained defaults.
* intake.py — the first free-text mission statement turned into answers the user confirms.
* regions.py — named target regions and ground stations (each with its source).
* store.py — designs saved as JSON under data/builder (never inside an optimiser project).

Every engineering value carries its provenance: the user's answer, the user's statement, a default (ASSUMED, with
its reason), or a value derived by an equation (analysis package, with its inputs and sources).
"""
