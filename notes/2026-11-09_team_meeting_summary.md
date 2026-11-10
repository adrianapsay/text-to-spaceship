# Team meeting, Nov 9 2026 (Adrian, Dadmehr, Sebastian, Huai-Yi)

## Decisions and action items for Dadmehr's thread
1. Order study: run the same part sets in many orders for the top 3 to 5 algorithms; measure how much each algorithm depends on order; then test a heuristic order (big, simple, convex first; concave last) against random orders. Random orders are the control (Sebastian).
2. Add a few more algorithms if any remain worth adding; drop the ones with no niche after interpreting the data.
3. Interpret the existing data (benchmark, scrabble, literature) and write down which algorithms to keep.
4. Catalog: grow a little, otherwise paused; keep it a pure catalog (no algorithms, no visualization inside it).
5. Compress the presentation for Douglas to about half; Adrian does brief slides plus MCP/CLI demo; coordinate by text before the meeting (Wednesday).
6. Fill out the objectives/tasks Douglas posted in Slack; check the "third brain" items from the last meeting.

## Open questions raised
- Which metric matters most (density vs aspect ratio vs contacts vs thermal spacing). All current algorithms optimize density only; other metrics are measured, not optimized.
- Fixed parts and incremental re-packing: stochastic/search algorithms can take fixed parts naturally; deterministic constructive ones need constraints. Needs thought before building.
- Per-part algorithm selection, sequencing algorithms, weighted multi-objective packing (Adrian).
- Who is the end user (NASA HWO team vs small teams/universities)? Ask Douglas. Changes whether a COTS catalog matters.
- Live web lookup of parts vs curated catalog: curated for research (reliability), live lookup as a later demonstration.
- Agent-in-the-loop test budgeting (stop early when one algorithm clearly wins) needs an API; Adrian testing an MCP/CLI route before Thursday.

## Questions for Douglas
- Who is the end user?
- Is a parts catalog in scope, or only user-supplied custom CAD?
- API access for an embedded agent.
