"""Agent evals: real Claude, fixed fake market data, checks on what it did and said.

    uv run python -m evals                 # all cases (about $0.30-0.60 of Claude usage)
    uv run python -m evals what_if trade   # only cases whose name contains one of these words

Runs against a separate local database (foxhood_eval), never the dev or production one. Not part of CI,
so it never spends money by accident."""
