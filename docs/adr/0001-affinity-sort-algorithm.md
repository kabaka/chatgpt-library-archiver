# Tag Affinity Sort Algorithm

* Status: Accepted
* Date: 2026-05-02
* Deciders: chatgpt-library-archiver maintainers

## Context and Problem Statement

The static gallery viewer currently sorts items by date or title only.
Users browsing large galleries want a "topical" sort mode that places
images sharing tags adjacent to one another, so scrolling reveals visual
clusters rather than a chronologically-shuffled mix. We need an
ordering algorithm that:

* Runs as part of the existing gallery build (Python, server-side),
* Persists a stable per-item ordinal in `metadata.json` so the JS
  viewer can sort in O(N log N) at load time,
* Is dependency-free (the project already deliberately ships a
  minimal dependency footprint),
* Is deterministic so that two builds with identical metadata produce
  identical output (important for diffability and tests),
* Scales acceptably to galleries up to ~20 000 items (the practical
  upper bound for a single ChatGPT user library).

## Decision Drivers

* Pure-Python: avoid pulling in `numpy`, `scipy`, `umap-learn`, etc.
* Deterministic: same input → same output, no randomness or
  floating-point order sensitivity.
* Linear-ish scaling: O(N²) is acceptable up to ~20 k items; anything
  worse is not.
* Code size: small and reviewable (≤100 LOC).
* Compute lives server-side (Python build step), not in JS at load
  time, so the algorithm can be slightly heavier in exchange for a
  trivial viewer.

## Considered Options

1. **Greedy nearest-neighbor traversal over Jaccard similarity, seeded
   by the densest tag cluster.** (Chosen.)
2. Hierarchical clustering (e.g. agglomerative single-linkage).
3. 1-D embedding via MDS / UMAP / t-SNE.
4. TF-IDF + cosine + greedy traversal.
5. Bucket sort by primary (most-frequent) tag.
6. Travelling-Salesman-Problem-style global optimum (2-opt, etc.).

## Decision Outcome

Chosen option: **(1) greedy nearest-neighbor over Jaccard, seeded by
the densest cluster.**

The algorithm:

1. Drop items with empty tag lists; assign them `affinity_index =
   None` so the JS viewer can park them at the end.
2. Build a `frozenset[str]` per remaining item.
3. Choose the seed: identify the globally most-frequent tag
   (deterministic tiebreak: lexicographic name), then among items
   containing that tag pick the one with the largest tag set
   (tiebreak: lexicographic id).
4. Iteratively, pick the unvisited item with the highest Jaccard
   similarity to the current item. Tiebreaks: shared-tag count desc,
   `created_at` desc, lexicographic id.
5. Assign the 0-based traversal position as `affinity_index`.

The work happens inside `generate_gallery()` so every gallery build /
metadata save refreshes the index. A standalone
`compute_affinity_indices(items)` function is exported for future
management subcommands (planned in
[`docs/reviews/2026-05-01-feature-batch/PLAN.md`](../reviews/2026-05-01-feature-batch/PLAN.md)
Task 1) that need to recompute without rebuilding the HTML.

### Consequences

Good:

* Pure-Python, ~80 LOC, no new dependencies.
* O(N²) worst case but in practice O(N · k · avg_tag_overlap) thanks
  to set intersection short-circuiting; well under a second for
  10 000 items on a laptop.
* Deterministic (every tiebreaker is total and reproducible).
* Output is a single integer per item — trivial to consume in JS and
  to query from CLI tools (`gallery query --sort=affinity`).
* No special handling needed in the viewer: the sort comparator is a
  three-line `null`-aware integer compare.

Bad / accepted tradeoffs:

* Greedy NN can produce a locally-optimal but globally-suboptimal
  path (classic TSP failure mode). For a sort *order* this is fine —
  the goal is "neighbors share tags", not a globally minimum-cost
  tour.
* O(N²) puts a soft ceiling around ~50 000 items; beyond that we'd
  need to fall back to bucket-by-primary-tag (deferred until the
  ceiling is hit).

## Pros and Cons of the Options

### Hierarchical clustering (rejected)

Pros: better global cluster structure than greedy.

Cons: O(N²) memory, ~200 LOC of edge-case-laden code, requires
flattening a dendrogram into a 1-D order (which itself is a leaf-
ordering optimization problem). The marginal quality gain is not
worth the complexity and review burden, and the natural
implementation paths drag in `scipy`.

### MDS / UMAP / t-SNE 1-D embedding (rejected)

Pros: produces a smooth continuum, arguably the highest-quality
ordering possible.

Cons: pulls in `numpy` plus a heavy embedding library
(`umap-learn`, `scikit-learn`); stochastic by default (defeats
determinism); slow on large N; far outside the project's "minimal
deps" posture.

### TF-IDF + cosine + greedy (rejected)

Pros: Slightly better discrimination than Jaccard when tag
frequencies are skewed.

Cons: Same algorithmic shape as the chosen option but adds an IDF
weighting step and floating-point cosine math. Tags in this corpus
are short normalized strings (already deduped per item), so the
binary set-overlap that Jaccard captures is the relevant signal.
Cosine adds complexity for marginal gain. Jaccard's
`|A∩B| / |A∪B|` is also exactly the human intuition behind "these
images share tags".

### Bucket sort by primary tag (rejected as primary, kept as future fallback)

Pros: O(N log N), trivial code.

Cons: Coarse — items inside a bucket are unordered relative to
their secondary-tag overlap. Boundaries between buckets are jarring.
Acceptable as a fallback above ~50 k items, where O(N²) becomes a
real concern; not the right default.

### Global TSP-style optimum (rejected)

Pros: Mathematically optimal "tour" through the similarity graph.

Cons: Massive complexity for a use case where the user just wants
neighbors to look related. 2-opt swaps would add hundreds of LOC and
make the build noticeably slower. Greedy NN's local mistakes are
imperceptible in practice.

## Seed Choice: Why "Densest Cluster"

We considered four seed strategies:

1. **Densest cluster (chosen)** — item with the most tags in the most-
   frequent global tag. Anchors the traversal at the busiest part of
   the similarity graph; the longest, densest run of overlapping
   neighbors ends up at the start, which is the most useful place
   for a default-sorted view.
2. **Lowest-degree seed** — item with the fewest connections. Tends
   to start the tour in a sparse outlier and snake inward; the user
   sees outliers first, which is the opposite of what we want.
3. **Deterministic-by-id (e.g. min id)** — fully arbitrary; no
   correlation with content.
4. **Arbitrary first item** — order-dependent; defeats determinism if
   input order ever shifts.

The densest-cluster seed is also deterministic (the global most-
frequent tag has a lexicographic tiebreaker, the seed within that
tag has a tag-set-size + id tiebreaker), so we get the visual benefit
without sacrificing reproducibility.

## Server-Side Precompute vs. JS Runtime

We chose to compute `affinity_index` in Python during `gallery
build` rather than in the viewer at page-load time:

* **Performance**: O(N²) at load on a phone is unacceptable for
  galleries even of a few thousand items.
* **Simplicity**: the JS viewer becomes a 3-line null-aware integer
  compare; no need for ship Jaccard / seed-pick logic to the browser.
* **Reuse**: the precomputed field is consumable by external CLI
  tools (planned `gallery query --sort=affinity`).
* **Cost**: rebuilds already touch every item in `metadata.json`;
  adding the computation is a negligible incremental cost on the
  build path that the user already pays for.

The cost is one integer per item in `metadata.json` (worst case ~6
bytes / item). For 20 000 items that's ~120 kB — trivial.
