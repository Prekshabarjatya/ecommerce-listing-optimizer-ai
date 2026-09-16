# Evaluation, cost, and known limitations

This document exists because the pipeline shipped with no way to answer
three questions an interviewer (or a future maintainer) will ask
immediately: *how do you know the critic's score means anything, what does
a run actually cost, and can you tell a prompt change made things better or
worse?* Before this, the answer to all three was "you can't." This is what
changed and how to use it.

## 1. The critic's self-correlation bias

`critic_agent.py` scores `content_agent.py`'s output. Left unconfigured,
both call the same model (`GROQ_MODEL`, via `agents/llm_client.py`) — the
same model grading its own homework. That's not a hypothetical concern:
a model's blind spots (a claim it thinks sounds fine, a phrasing pattern it
over-uses) are exactly the kind of thing it's least likely to flag in its
own output, so a high critic score is weaker evidence of quality than it
looks, precisely because generator and judge share failure modes.

**Mitigation shipped:** `critic_agent.py` now reads `CRITIC_MODEL` from
`agents/llm_client.py`, which defaults to `GROQ_MODEL` but can be pointed at
a different model via the `GROQ_CRITIC_MODEL` env var (see
`.env.example`). Using a different model family for the critic doesn't
eliminate correlation (both models were still trained on overlapping data
and instruction-tuned toward similar notions of "good copy"), but it's a
real, cheap step away from the worst case of literally the same weights
marking their own work.

**What this doesn't fix:** an independent LLM judge is still an LLM judge,
not ground truth. The only way to know whether *any* critic configuration
actually tracks listing quality is to check it against a human's judgment —
which is what the eval harness (§3) is for. Say this plainly in an
interview rather than implying the separate-model change alone solves it.

## 2. Prompt versioning and how to run an ablation

Each agent module now declares a `PROMPT_VERSION` constant next to its
`SYSTEM_PROMPT` (`audit-v1`, `content-v1`, `critic-v1` as of this writing).
Every `listing_optimizations` row stores which prompt version and which
model produced it (`audit_prompt_version`, `content_prompt_version`,
`critic_prompt_version`, `generation_model`, `critic_model` — added via the
same guarded-`ALTER TABLE` migration pattern already used for
`human_decision`, so it applies to a database you already have).

To run an ablation:

1. Change a `SYSTEM_PROMPT` and bump its `PROMPT_VERSION` (e.g.
   `content-v2`) in the same commit — the version string is the only thing
   that makes old and new runs distinguishable later.
2. Re-run the pipeline (`scripts/run_pipeline.py`, or
   `scripts/run_eval.py --build-set --force` against the fixed eval set —
   see §3).
3. Compare runs grouped by `content_prompt_version` — critic score
   distribution, blocked-claim rate, and (if you've labeled any) human
   agreement from `scripts/run_eval.py --agreement`.

There's no built-in query for step 3 yet beyond what `run_eval.py` computes
across *all* runs; grouping by prompt version for a two-way comparison is a
few lines of SQL (`GROUP BY content_prompt_version`) against
`listing_optimizations`, deliberately left manual rather than building a
comparison UI for two prompt versions that don't exist yet.

## 3. Cost and latency

Every LLM call (audit, content, critic) is timed and its token usage
recorded to a new `llm_call_log` table (`agents/telemetry.py`,
`app/database/repository.py::insert_llm_call_log`), keyed to the
`listing_optimizations` run it belongs to. Cost is *estimated* from a
hard-coded per-model rate table in `telemetry.py` — Groq's actual pricing
moves, so treat the dollar figure as directional, not a bill.

```bash
python scripts/usage_report.py                    # totals by agent/model/prompt version
python scripts/usage_report.py --seller-sku SKU    # every call made for one SKU
```

Runs from before this change have no `llm_call_log` rows — usage logging
starts from here forward, it isn't backfilled.

## 4. Eval set: agreement and error-mode analysis

`scripts/run_eval.py` is the harness. Two of its three modes need no human
labels and work today against whatever's already in the database:

```bash
python scripts/run_eval.py --error-modes
```

This reports, across every run so far: the approval-status mix, average
critic sub-scores overall and split by verdict (which of seo /
readability / completeness / brand_consistency is systematically the weak
one), the most common audit issues, which blocked claims fire most often
and on what fraction of runs, and the correlation between the pre-generation
`audit_score` and the post-generation `critic_overall` (near zero is the
expected/healthy answer — it would mean the rewrite doesn't just track how
bad the original listing already was).

The third mode is the one that actually validates the critic against a
human, and it's a two-step, honest process rather than a single command,
because fabricating the human side would defeat the point:

```bash
python scripts/run_eval.py --build-set --n 20
# -> samples a fixed set of seller_skus (seeded, so re-running reuses the
#    same set instead of a new random one -- required for before/after
#    prompt comparisons to mean anything), ensures each has a run, and
#    writes eval/human_labels_template.csv with the generated copy and the
#    critic's own score alongside blank human_score / human_pass / human_notes
#    columns.
```

Fill in `human_score` (0-100, your own read of `generated_title` +
`generated_description`) and `human_pass` (would you actually ship this?)
for each row by hand, save it (e.g. `eval/human_labels_filled.csv`), then:

```bash
python scripts/run_eval.py --agreement eval/human_labels_filled.csv
```

This reports mean absolute error and correlation between `critic_overall`
and `human_score`, plus a 2x2 breakdown at the approval threshold (critic
>= 90): both approve, both hold back, critic-approved-but-human-wouldn't
(the dangerous direction — an unearned auto-approval), and
critic-held-back-but-human-would-have (over-cautious, just costs a human
review cycle). Twenty labeled rows is not a statistically powered study —
it's enough to catch "the critic is systematically 15 points too generous"
or "the critic never flags weak brand voice," which is the actual goal
here: surfacing a concrete, fixable failure mode, not producing a
publishable accuracy number. `eval/eval_set.csv` and any labels file are
generated from real catalogue listings and are gitignored for the same
proprietary-data reason as `data/raw/`.

## Where this leaves things

What's still missing, stated plainly rather than left implicit: there is
still no automated regression check that a prompt change didn't make
things worse (that's a human re-running `--agreement` and reading it,
not a CI gate); the cost table is an estimate; and a critic on a different
model is a mitigation for self-correlation bias, not a proof of
independence. All three are one honest step better than before, not solved.
