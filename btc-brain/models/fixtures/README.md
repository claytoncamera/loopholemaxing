# Phase 3 fixtures

Synthetic, deterministic datasets used to:

  * exercise the training/validation pipeline end-to-end without network,
  * power the Phase 3 unit tests,
  * generate the *example* artifacts in `btc-brain/models/public/` so the
    schema is reviewable.

`fixture_only: true` is set on every artifact derived from these. They
make no claim about real BTC market behaviour.
