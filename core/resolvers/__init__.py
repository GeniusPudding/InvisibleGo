"""Pluggable dead-stone resolvers.

A resolver is an `async (GameSession) -> set[Point] | None` callable —
the same shape `transport.session.DeadStoneResolver` expects.
Implementations:

- `benson_safety_filter`        Wraps another resolver; vetoes any
                                  proposal that includes a Benson-alive
                                  stone (so a flaky NN can't kill an
                                  unconditionally-alive group).
- `chained`                     Tries resolvers in order; falls through
                                  on EngineUnavailable.
- `katago_resolver`             KataGo via GTP `kata-analyze ownership`.
- `gnugo_resolver`              GNU Go via GTP `final_status_list dead`.
- `montecarlo_resolver`         Pure-Python random-playout estimator
                                  (no external deps; for tests).

The interactive marker/approver flow lives in `transport.session` and
is the default fallback when every automatic resolver is unavailable.
"""
from core.resolvers.benson import benson_safety_filter
from core.resolvers.chain import EngineUnavailable, chained
from core.resolvers.gnugo import gnugo_resolver
from core.resolvers.gtp import GtpEngine, GtpProtocolError
from core.resolvers.katago import katago_resolver
from core.resolvers.montecarlo import montecarlo_resolver

__all__ = [
    "EngineUnavailable",
    "GtpEngine",
    "GtpProtocolError",
    "benson_safety_filter",
    "chained",
    "gnugo_resolver",
    "katago_resolver",
    "montecarlo_resolver",
]
