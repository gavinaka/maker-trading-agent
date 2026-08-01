# Daily Workflow vNext

`runtime_vnext` is an isolated shadow-production kernel. It does not replace
the legacy `runtime` package or change any automation until the cutover
acceptance contract in `governance/vnext_daily_workflow.md` is met.

## Product contract

One user request starts one report task. Internally the task advances through
five checkpointed stages:

```text
evidence -> reasoning -> decision -> report -> delivery
```

The business gates are:

1. evidence integrity;
2. reasoning consistency;
3. risk and execution closure;
4. delivery integrity.

After a run reaches `complete`, `shadow_complete`, or `retired`, the artifact
store makes a best-effort, non-blocking write of `sample_outcome.json`.  This is
an immutable mechanical export for the external Technical expert evaluator,
not a fifth production gate.  It contains counts, hashes, contract booleans,
defect-code fingerprints, and the sealed rate-expectation provider/method/source
class only; production stages must never read it.  A new
`methodology-manifest-v3` run exports `vnext-sample-outcome-v6` with the sealed
semantic, release, and combined-manifest hashes.  v1-v5 artifacts remain
immutable read-only legacy inputs; a legacy v2-manifest run that is missing an
outcome still emits v5 and never invents a semantic identity.
Only `cme_fedwatch_ui + cme_target_rate_probability + cme_canonical` can add a
clean stability sample.  Kalshi Plan C remains an observation even when every
mechanical contract passes; it adds no stability increment, switch eligibility,
or clean evidence.  This does not suppress engineering defects: two independent
runs in the same authority epoch with the same reproducible Plan C failure
fingerprint may still become `candidate_defect`, without automatic repair or a
new hard gate.

Report compilation is deterministic and is not a new business gate. A compile
failure retries only `report`; a Word or Notion failure retries only
`delivery`. Earlier certified artifacts remain immutable and hash-bound.

## State layout

```text
runtime_state_vnext/<date>/<slot>/<run-id>/
  run.json
  methodology_manifest.json
  host_capability.json
  checkpoint.json
  events.jsonl
  evidence/attempt-001/
  reasoning/attempt-001/
  decision/attempt-001/
  report/attempt-001/
  delivery/attempt-001/
  delivery_assets/
  manual_reviews/
  retirement.json       # only after explicit retirement
```

An attempt directory is append-once. Retrying creates `attempt-002`; no file
is quarantined, restored over another file, or silently overwritten. Every
attempt records its process/thread owner. A dead owner is sealed with an
`orphaned.json` terminal record before a new attempt is created; a live owner
blocks duplicate work.

The short-lived controller lock records its PID and lock ID. If a process is
hard-stopped, the next controller verifies that the PID is dead, preserves the
orphan lock as audit evidence, and resumes from the sealed checkpoint. A live
process lock is never stolen.

## Internal CLI

The CLI is an internal deterministic boundary, not a request for the user to
manually operate each stage:

```text
py -m runtime_vnext.cli begin --date <date> --slot <slot> --run-mode <shadow|production> --authorization-ref <explicit-approval-reference>
py -m runtime_vnext.cli host ...
py -m runtime_vnext.cli capture ...
py -m runtime_vnext.cli replay-evidence ...
py -m runtime_vnext.cli reasoning-contract-preflight ...
py -m runtime_vnext.cli reasoning-scaffold ...
py -m runtime_vnext.cli reasoning ...
py -m runtime_vnext.cli decision ...
py -m runtime_vnext.cli compile ...
py -m runtime_vnext.cli word-qa-export ...
py -m runtime_vnext.cli word-qa-approve ...
py -m runtime_vnext.cli word-qa-reject ...
py -m runtime_vnext.cli delivery ...
py -m runtime_vnext.cli shadow-delivery ...
py -m runtime_vnext.cli resume-review ...
py -m runtime_vnext.cli retire ...
py -m runtime_vnext.cli status ...
```

The machine-owned pre-cutover delivery sequence is
`compile -> word-qa-export -> word-qa-approve -> shadow-delivery`.
word-qa-export owns the run-local render: it derives the certified report and
run identity, renders under the controller lock, verifies the report and DOCX
hashes, and only then creates a Word-QA attempt. Page inspection and approval
still judge the final product. This delivery orchestration does not alter
evidence, reasoning, scoring, decision, report content, or presentation
contracts.

The daily-report skill owns these calls only when an explicitly approved task
selects the isolated vNext engine.  Legacy SOP/context transport must not be
mixed into that run.  Automations remain paused until shadow acceptance and
cutover approval.

Every newly created run is `daily-run-vnext-v2`. Its mode is immutable, and
the explicit approval reference is persisted only as a SHA-256 digest plus the
fixed authorization kind for that mode; raw approval text is never stored.
The current authority profile is additive within that run schema and seals
exactly `semantic_contract_sha256`, `release_sha256`, and
`methodology_manifest_sha256`.  It never mixes those fields with the legacy
`methodology_sha256` combined binding.  Semantic identity alone defines the
sample epoch; release and combined identities remain mandatory rollback and
bisect evidence, so a release-only refactor does not silently reset the clean
cohort.
Legacy v1 terminal runs remain readable for audit only. A legacy v1
non-terminal run cannot infer a mode or resume execution and must be explicitly
retired before replacement.

Capture is market-evidence-only: it never reads a pretrade gate, Notion,
personal holdings, or order state. A shadow run never creates, loads, or
consumes the production pretrade contract and therefore always has
`live_execution_allowed=false` and `execution_action=not_attempted`. A
production run may consume the vNext-native, same-day pretrade contract only
at decision time. That contract may change execution authorization/action, but
must never change the certified plan state, direction, score, win rate, entry
range, targets, stop, defense, or main-account reasoning.

## Legacy capture adapter

`legacy_capture_adapter.py` verifies the current immutable capture manifest and
maps its files into `evidence-snapshot-v1`. It never recaptures, edits, moves,
or copies evidence. This lets vNext shadow tests reuse a successfully captured
slot without reopening the collection stage.

## Non-negotiable boundaries

- New vNext runs request exactly `gpt-5.6-sol` with exactly `xhigh` effort. An
  observed host capability of `xhigh`, `max`, or `ultra` may satisfy the
  `>= xhigh` capability check, but the sealed run request remains `xhigh` and
  correctness must not depend on a higher observed value. Historical sealed
  efforts remain immutable; the legacy engine retains its separate exact
  `high` request contract.
- Six sources are mandatory, including TradingView 1D/4H/1H/15m.
- ETF, VRVP, liquidity-hunt and liquidation-map logic are additive and each
  must be represented in the certified reasoning graph; collecting the files
  without using them does not pass.
- Reasoning requires base, counter, and invalidation scenarios.
- `reasoning-submission-contract-v6` and
  `reasoning-submission-scaffold-v6` separate model judgment from
  `reasoning-server-projection-v4`. All 54 methodology leaves must be
  exhaustively and exclusively classified; an unclassified leaf hard-stops
  preflight. The controller owns only deterministic identity, mirror, constant,
  and complete account/scenario subtree projections after the normal reasoning
  attempt opens. The model retains exactly eight business leaves: four
  `independent_synthesis` selections, three per-event impact/effect/counter
  leaves, and `transition_summary`. Per-event `selected_event_sha256` is only a
  sealed-top3 row key; runtime may resolve the same-hash realization claim but
  may not rewrite or reorder that key. The controller also projects each
  source's sealed-artifact `evidence_refs` inventory, deterministic structured
  bindings, and visual-artifact self-hashes. That inventory is an allowlist,
  not proof that the model read every artifact; visual citations, crops, metric
  coverage, facts, visual interpretation, claim ancestry, current basis, future
  triggers, thesis, counterevidence, and invalidation remain model-owned and
  fail closed. The scaffold exposes exact source shapes plus
  `claim-topology-v1`; runtime never injects support edges, deletes extra fields,
  or fills missing model-owned fields. Counterevidence and invalidation are
  sibling controls: invalidation must reach its account's market regime but
  does not depend on the strongest-counter claim, while `cannot_do` must still
  reach all four Maker closure nodes. Typed enum and closed-code fields are the
  sole control truth; corresponding free prose is audit-only and is never
  interpreted by keyword as a second state.
- Empty visual metric objects or arrays are explicit observable-absence leaves
  and still require a bounded same-source citation; `[]` is not an uncited
  escape hatch.
- Current-basis polarity supports directional and explicitly non-directional
  theses. For `long|short`, only the opposite direction is counterevidence. For
  Main `neutral` or Maker `observe`, directional evidence counters remaining
  non-directional, and one strongest counter must identify one coherent
  alternative direction; neutral/supportive clauses cannot pad it.
- `account-trigger-logic-v5` preserves model-owned targets while projecting
  only the canonical relative-pair operators. A bound Coinglass target equal
  to its certified current value uses `equals_at_trigger`; a different target
  uses `becomes`; the paired Exocharts relation uses `equals_at_trigger`. The
  current truth is mode-aware: every `any` clause must be unsatisfied, while
  `all` needs at least one unsatisfied clause. Missing or ambiguous references
  fail closed, and projection may not
  add, delete, reorder, or alter any business clause.
- Plan-time conviction uses one closed sequence: an anchor whose `shared|maker`
  claim IDs jointly cover the Coinglass+Exocharts orderflow axis and the
  TradingView structural-position axis. Its `anchor_rationale` must equal the
  authority-owned `anchor_policy.canonical_rationale`; market-specific basis
  lives only in typed anchor claims and reachable sources, and the compiler may
  not preserve or invent free-text market explanation. A mandatory negative
  `adjustments[0].reason_code=maker_counter_current` adjustment covers every current Maker counter
  `current_basis` clause in order, with `disposition=adjusted` and empty
  `resolution_claim_ids`; ETF and fundamental adjustments may appear only after
  index 0; then only independent ETF and fundamental
  price-realization adjustments; then `final=anchor+sum(adjustments)`; only
  after final is sealed may the controller compare 60% and derive threshold or
  plan state. Main, thesis/regime/counter/cannot-do, fundamental, and ETF
  claims cannot anchor the rubric. FedWatch, footprint/orderflow,
  chart/structure, liquidation map, entry-price reach probability, order
  lifecycle, and risk math are
  not adjustment families. There is no `resolved_no_adjustment`, no optional
  bypass of the current counter, and no direct claim or typed-owner double
  counting. The final value must equal the decision field.
- Main-account and Maker reasoning remain separate.
- Each account's reasoning-stage `invalidation_path` owns an exact
  `structural-noise-buffer-v2`. A `certified` judgment binds a reachable
  current-run TradingView observation, account-allowed timeframe, same-frame
  visual evidence, mechanically locatable structural anchor, visible
  `noise_outer_boundary`, positive `price_distance`, and
  `risk_budget_input_used=false`; the final stop must be strictly outside that
  boundary. An unreadable visual basis uses the closed
  `visual_noise_envelope_not_readable` insufficient reason. Main `neutral` and
  Maker `observe` have no directional stop and instead require
  `not_applicable_non_directional_thesis`. Both insufficient paths keep
  anchor/boundary/distance null and force an `observe` decision. Every
  stop-basis identity, anchor, and distance field
  present in Decision must exactly equal the reasoning owner; Gate separately
  reads the reasoning status, visual evidence, and noise boundary and verifies
  the derived stop. Maker 3%, Main 8%, and R:R are later validation inputs and cannot shrink the
  structural stop. The compiler validates and projects the sealed judgment and
  may not infer one. No fixed minimum distance, ATR multiple, or risk-threshold
  backsolve is authority.
- No Agent-written `combined.md`; it is compiled from
  `canonical-report-model-v11`.  Account scenarios accept only the six
  `scenario-ownership-v1` rows (`id/account/scenario_type/owner_claim_id`);
  their visible Chinese condition, expected path, and analysis-state transition
  are projected deterministically from typed owners and closed transition
  codes. Execution lifecycle remains owned only by Decision and continuity.
  The compiler first derives one of four
  mutually exclusive Maker states from certified fields:
  `qualified_candidate`, `rejected_submitted_candidate`,
  `directional_thesis_only`, or `non_directional_observation`.  A non-empty
  `risk_plan` is the sole candidate-submission owner; direction or an attempted
  zone reference alone cannot create a candidate.  Rejected submissions retain
  their original lifecycle only as explicitly non-executable audit.  The two
  no-candidate states reject non-negated entry/order/fill/TP/cancel/stop
  lifecycle prose, and report evaluation reconstructs Maker summary/execution
  plus main authorization from sealed audit fields rather than trusting visible
  summaries.  The compiler derives the rate-expectation
  display name from sealed evidence metadata, never from provider prose.  CME
  is shown as the canonical source; Kalshi is visibly disclosed as the
  `KXFEDDECISION` Plan C observation source, including API data time, independent
  event-contract methodology, non-equivalence to CME, and observation-only
  status.  Tail buckets such as `cut_gt_25bp`, `hike_gt_25bp`, and
  `other_unlisted` are projected explicitly rather than hidden or relabelled.
  Compatibility is narrow: an immutable `evidence-snapshot-v1` with empty
  provider meta can only render as `provider_id=unknown`, visibly marked as a
  legacy read-only observation.  A current `evidence-snapshot-v2` with missing,
  mixed, or unsupported provider metadata fails closed and cannot be rendered
  or exported as a provider-qualified sample.
- Real cutover requires consecutive live shadow samples, not only unit tests.

Repeated reasoning failure enters `needs_review`. No stage can continue until
an explicit, hash-bound `manual-review-authorization-v1` record resumes the
failed stage. This keeps the hard stop real without creating an unrecoverable
workflow lock.

An unfinished run can release the global active-run position only through an
explicit, hash-bound `run-retirement-authorization-v1`. Retirement preserves
the run, attempts, checkpoint and audit events. It is blocked while a live
stage owner exists; no directory or evidence is deleted.

After that explicit retirement, the same date/slot may start one replacement
run. The new run records `supersedes_run_id`, and `current.json` moves
atomically only after the replacement initializes successfully. A running or
production-complete run can never be superseded through this path, and the
retired run remains fully auditable. During explicitly authorized shadow
acceptance only, `begin --allow-shadow-repeat` may also supersede an immutable
`shadow_complete` run in the same slot. It records the prior terminal status,
keeps every prior artifact and sample outcome unchanged, and never weakens the
Notion prohibition or production-complete boundary.

If a process dies after sealing `complete`, `shadow_complete`, or `retired` but before removing the
global active-run lease, the next `begin` reconciles that lease only while
holding the old run's controller lock and only after revalidating the sealed
run/checkpoint identity. A running or non-terminal run is never reclaimed.
The initial lease is separately marked `initializing` with its process owner;
if that process dies before the run becomes resumable, the lease is moved to
an orphan audit record before another run may claim the global position.

BlockBeats cards are compiled from the three hash-bound selected events in the
certified evidence snapshot. Their specifications and rendered PNG hashes are
report-stage outputs, so delivery cannot replace them with Agent-written or
uncertified cards. vNext Word/PDF/QA assets are written only under the run's
`delivery_assets/` directory and never into legacy shared output paths.

Delivery validation checks actual DOCX package parts, PDF signatures, PNG page
headers and dimensions, full-page inspection records, report hashes, and the
Notion page UUID/signature contract. A boolean PASS beside placeholder files
is insufficient. Both production and shadow delivery require an exact
`word-qa-vnext-v2` manifest bound to the current run id/hash/date/slot, an
approved Microsoft Word backend, a named reviewer, a timezone-aware review
time, and inspection of pages `1..page_count`. A passed manifest must use exact
`review_checklist_version=word-qa-semantic-review-v1`; its checklist must have
exactly `all_pages_inspected`, `no_clipping_overlap_or_missing_glyphs`,
`no_orphan_semantic_headings`, `critical_price_blocks_not_split`,
`six_source_sections_readable`, and `arabic_price_digits_preserved`, with every
value the boolean `true`. The Python approval API itself also requires
`confirm_visual_pass=True`; the CLI flag is not the only guard.

During pre-cutover shadow acceptance, `shadow-delivery` uses a separate
`shadow-delivery-model-v1` contract. It validates the same local report,
DOCX/PDF, every inspected page image, card specification, and three card PNGs,
but requires an explicit `not_attempted` Notion sentinel. It rejects any
Notion publish or readback claim and seals the run as `shadow_complete` with
`notion_published=false`. The production `delivery` command and its Notion
requirements are unchanged.
