"""The AI incident-analysis layer.

The nine deterministic checks decide WHAT is wrong; this package makes sense of
it: connects related breaches, ranks severity (with a deterministic floor),
writes remediation grounded in the Ops team's own knowledge files, and explains
cross-metric impact from a declared dependency graph.

It runs on whichever model the user selected (via the LLM provider layer and
their fallback chain), records usage, and enforces plan/user limits — so the AI
analysis is governed exactly like every other model call.
"""
