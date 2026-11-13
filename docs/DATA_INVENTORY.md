# Data inventory (Step 0)

Generated 2026-11-13 from MuseCell (read-only, commit `313e7f5` as stated by the owner). Reproduce with
`python tools/inventory.py` (coverage, writes `docs/inventory.json`), `python tools/data_schema.py` (table schemas),
`python tools/copy_raw.py` (copies inputs to `data/raw/` and writes `data/PROVENANCE.md`) and
`python tools/source_table.py` (table at the bottom).

**Decision: PLAN A**: 38 of 38 compounds have a usable transcript (threshold 30). All 38 come from the preferred
source (agent v5, Scientist `muse-spark-1.3`, budget 4, finished).

## 1. Index files

| file | rows | fields |
|---|---|---|
| `MuseCell/eval/agent_runs.jsonl` | 323 | run_id, specimen_id, compound, truth_moa, budget, models{scientist, microscopist, reviewer, segmentation, [provider, atlas, agent]}, status, error, agent_moa, correct, first_moa, first_correct, review, wells_used, turns, cost_usd, latency_s, citations_*, report, leak_hits; v5 rows add call_source, scientist_moa, scientist_correct |
| `MuseCell/eval/open_world_runs.jsonl` | 38 | as above, agent `v5-open`, plus vote_moa, classes_seen, leaves_vote, leaves_all_refs, says_dont_fit, says_spans, microscopist_named_truth |

361 rows, 361 unique run ids, 38 compounds, 12 MoA classes. `review` is `approve` (243), `request_experiment` (115)
or null (3). `status`: finished 353, failed 8. In v5 rows `agent_moa` is the NSC protocol vote
(`call_source: protocol`); the Scientist's own call is `scientist_moa`.

## 2. Transcripts (`run_<id>.jsonl`)

Search: `Get-ChildItem $HOME -Recurse -Filter 'run_*.jsonl'`. All hits are inside MuseCell; nothing under
`AppData\Local\Temp\claude` or "Local Settings". `DATA_DIR` (`~/musecell-data`) holds no transcripts.

| directory | files |
|---|---|
| `MuseCell/runs/eval` | 331 |
| `MuseCell/runs/eval_open_world` | 38 |
| `MuseCell/runs` | 23 |
| `MuseCell/demo/runs` | 4 |
| total | 396 files, 392 unique ids |

The 4 duplicate ids (`run_206290f4c32e`, `run_64e9e01ca04e`, `run_9afbd903a2d2`, `run_c1d73af89f4d`) sit in both
`runs/` and `demo/runs/`. 31 unique transcripts are not in any index file (23 in `runs/`, 8 in `runs/eval/`); they are
not used. No file was reported cloud-only or unreadable by OneDrive (all have attribute `Archive`).

Format: one JSON event per line: `{run_id, seq, ts, type, data}`. Types: run_started, thinking, cost_updated,
tool_call, tool_result, budget_updated, hypotheses_updated, conclusion, review, protocol_call (v5), unblinded,
verdict, report_ready, run_finished. `tool_result.data` = {call_id, name, ok, error, evidence_id, kind, summary,
image_ids, data, cost_usd}. Relevant payloads:

- `acquire_well` (kind `well`): concentration_uM, replicate, segmentation.cells_measured, `profile_z` (24 features,
  robust z vs same-plate DMSO), top_deviations.
- `describe_phenotype` (kind `phenotype`): Microscopist (vision model) report: cell_density, observations
  [{channel, finding, agrees_with_measurements}], candidate_mechanisms [{moa, why}], notable_cells, uncertainty. The
  Microscopist sees images, the measured top deviations and the MoA list, **not** atlas results
  (`backend/app/agent/tools.py::describe_phenotype`), so its text is NSC-free by construction.
- `dose_response` (kind `dose_response`): feature, points [{concentration_uM, median, n_wells}], spearman_rho,
  p_value.
- `compare_to_reference_atlas` (kind `atlas`): neighbors [{compound, concentration_uM, moa, similarity}],
  moa_summary, and in v5 an `nsc` block (1-NN per acquired well, majority vote). Reference compound names are
  present in the raw data; they are stripped from our evidence.
- `review`: {round, model, verdict (approve | request_experiment), critique, requested_experiment}.

### Coverage per (index, agent version, Scientist model, budget)

| index | agent | Scientist | budget | rows | with transcript | finished |
|---|---|---|---|---|---|---|
| agent_runs | v1 (no agent field) | muse-spark-1.3-contributor | 2 | 38 | 38 | 38 |
| agent_runs | v1 (no agent field) | muse-spark-1.3-contributor | 4 | 38 | 38 | 38 |
| agent_runs | v1 (no agent field) | muse-spark-1.3-contributor | 6 | 38 | 38 | 36 |
| agent_runs | v1 (no agent field) | meta-models/muse-spark-open-1026 | 4 | 38 | 38 | 35 |
| agent_runs | v2 | meta-models/muse-spark-open-1026 | 4 | 19 | 19 | 17 |
| agent_runs | v3 | meta-models/muse-spark-open-1026 | 4 | 38 | 38 | 37 |
| agent_runs | v4 | meta-models/muse-spark-open-1026 | 4 | 38 | 38 | 38 |
| agent_runs | v5 | meta-models/muse-spark-open-1026 | 4 | 38 | 38 | 38 |
| agent_runs | v5 | muse-spark-1.3 | 4 | 38 | 38 | 38 |
| open_world | v5-open | muse-spark-1.3 | 4 | 38 | 38 | 38 |

Every indexed run has a transcript (361/361).

## 3. Data tables

`MuseCell/data/` contains only `index.parquet`. The feature tables, atlas and metadata live in DATA_DIR
(`C:\Users\Oleksandra\musecell-data`, from the `DATA_DIR` line of `backend/.env`).

| file | rows | content |
|---|---|---|
| `MuseCell/data/index.parquet` | 3096 fields | field_id, plate, well, field, compound, concentration_uM, moa, moa_annotated_conc, replicate, role, raw/npy/png paths |
| `DATA_DIR/processed/atlas/wells.parquet` | 1228 wells (898 treated, 330 DMSO) | plate, well, compound, concentration_uM, moa, moa_annotated_conc, replicate, role, well_key, field_ids, thumbnail_field_id, 24 features (raw values), n_cells |
| `DATA_DIR/processed/atlas/wells_norm.parquet` | 1228 | same columns, features as robust z vs same-plate DMSO. **Identical to transcript `profile_z`** (max abs diff 0.005 over 131 matched wells = rounding) |
| `DATA_DIR/processed/atlas/treatments.parquet` | 304 | per (compound, dose) medians of the 24 features |
| `DATA_DIR/processed/atlas/field_features.parquet` | 3096 | per-field cell_count and fractions |
| `DATA_DIR/processed/atlas_resnet50_tvn/wells.parquet` | 1228 | well_key + 212-d ResNet50 (ImageNet) + TVN embedding |
| `DATA_DIR/processed/atlas_resnet50_tvn/treatments.parquet` | 304 (103 at annotated doses) | compound, concentration_uM, moa, moa_annotated_conc, n_wells, 212-d vector (the v5 atlas / NSC reference) |
| `DATA_DIR/metadata/BBBC021_v1_moa.csv` | 104 | compound, concentration, moa |
| `DATA_DIR/metadata/BBBC021_v1_compound.csv` | 113 | compound, smiles |
| `DATA_DIR/metadata/BBBC021_v1_image.csv` | 13200 | BBBC021 image metadata (not used) |
| `DATA_DIR/processed/{fields,cells,embeddings}` | 3096 dirs / 6192 / 3096 files | images and per-cell tables, ~5.6 GB (not used, not loaded) |

24 features: nuc_area, nuc_dna_integrated, nuc_dna_mean, nuc_eccentricity, nuc_solidity, nuc_form_factor,
nuc_major_axis, cell_area, cell_nuc_area_ratio, cell_roundness, cell_eccentricity, cell_solidity, cell_major_axis,
tub_mean, tub_std, tub_glcm_contrast, act_mean, act_std, act_glcm_contrast, act_tub_ratio, cell_count,
frac_mitotic_like, frac_large_nucleus, frac_multinucleate_proxy.

The 898 treated wells are exactly the 38 compounds; 320 of them are at BBBC021-annotated doses.

NSC check: our re-implementation (median of a well's 212-d vector, cosine to annotated reference treatments of the
other compounds) reproduces the per-well 1-NN class recorded in the transcripts for 152/152 acquired wells.

## 4. MoA labels (12)

Actin disruptors, Aurora kinase inhibitors, Cholesterol-lowering, DNA damage, DNA replication, Eg5 inhibitors,
Epithelial, Kinase inhibitors, Microtubule destabilizers, Microtubule stabilizers, Protein degradation,
Protein synthesis. Compounds per class: 3, 3, 2, 4, 4, 2, 3, 3, 4, 3, 4, 3.

## 5. API (from `backend/app/config.py`, `backend/app/llm.py`; not imported)

- OpenAI-compatible Chat Completions, `POST {base_url}/chat/completions`, base_url `https://api.meta.ai/v1`, bearer
  key (MuseCell: `MODEL_API_KEY`). Body: model, messages, max_tokens, optional tools / response_format
  (json_schema, strict) / reasoning_effort.
- Usage: `usage.prompt_tokens`, `usage.completion_tokens` (includes reasoning),
  `usage.completion_tokens_details.reasoning_tokens`. Spark reasons by default; reasoning shares `max_tokens`
  (MuseCell used 8000). Empty content with `finish_reason="length"` means the model ran out of tokens.
- Prices (USD / 1M in/out): muse-spark-1.3 1.25/4.25, muse-spark-1.3-contributor 0.10/0.20,
  muse-wonder-1.0 4.00/20.00. MuseCell refuses `-contributor` unless `ALLOW_CONTRIBUTOR=true` because Meta may
  train on those prompts (only public BBBC021 data goes into ours).
- Retries: 429 / 5xx / connection / timeout with exponential backoff (base 1 s, max 30 s, honours retry-after).
- `seed` and `temperature` were **never probed** in MuseCell (DECISIONS.md documents only `reasoning_effort`). Whether
  the API accepts them is unknown; see README "API parameters".
- Observed output sizes (MuseCell cost ledger `DATA_DIR/cache/costs`, Scientist decision turns): mean ~1.0-1.5k
  completion tokens incl. reasoning, p99 ~3-4k, max 8000 (one run spent all 8000 on reasoning).

## 6. Plan A source per compound

Rule: among finished `agent_runs.jsonl` rows with agent `v5`, Scientist `muse-spark-1.3`, budget 4 and a transcript,
the one with the latest `run_started`; else the latest finished run with a transcript (never needed). Events
used: `tool_result`s strictly before the first `conclusion` and before `unblinded`.

| compound_id | true MoA | source run | source Scientist first call | wells/phenotype/dose/atlas blocks |
|---|---|---|---|---|
| s_07f98c80cd | Actin disruptors | run_09c0dd1caca0 | Eg5 inhibitors (wrong) | 4/1/2/2 |
| s_5a98540349 | Actin disruptors | run_45bf62c06860 | Actin disruptors (right) | 4/1/3/2 |
| s_a744010448 | Actin disruptors | run_82f46ddee170 | Actin disruptors (right) | 4/1/2/2 |
| s_46227421e8 | Aurora kinase inhibitors | run_088274154db2 | Aurora kinase inhibitors (right) | 4/1/2/2 |
| s_ef2246eac4 | Aurora kinase inhibitors | run_b1a34ff37269 | Aurora kinase inhibitors (right) | 4/1/2/2 |
| s_f499767749 | Aurora kinase inhibitors | run_3050c81af35b | Aurora kinase inhibitors (right) | 4/1/1/2 |
| s_3069b9414e | Cholesterol-lowering | run_d0cbb5627ad9 | Cholesterol-lowering (right) | 4/2/3/2 |
| s_dace923f5f | Cholesterol-lowering | run_c845baa04e62 | Cholesterol-lowering (right) | 4/1/2/2 |
| s_79cc880b6c | DNA damage | run_f2df19bf06d0 | DNA damage (right) | 4/1/3/3 |
| s_89e4b24a88 | DNA damage | run_958d2b448a72 | DNA damage (right) | 4/1/3/2 |
| s_8dd1eb85a8 | DNA damage | run_1c19f9ea2a5c | Aurora kinase inhibitors (wrong) | 4/1/2/2 |
| s_a17f2e4647 | DNA damage | run_5f64019f1bd2 | DNA damage (right) | 4/1/3/2 |
| s_10190ff204 | DNA replication | run_1ca08d406441 | Microtubule stabilizers (wrong) | 4/3/2/2 |
| s_6f5cd54991 | DNA replication | run_4f75f2448c22 | DNA replication (right) | 4/1/2/2 |
| s_826e117c63 | DNA replication | run_a80bd9e6b080 | DNA damage (wrong) | 4/1/2/2 |
| s_9b92bf868e | DNA replication | run_3ce38eaf5160 | Microtubule stabilizers (wrong) | 4/1/3/2 |
| s_7526ba207c | Eg5 inhibitors | run_a0436f5fcbc5 | Eg5 inhibitors (right) | 4/1/1/3 |
| s_f0826fee65 | Eg5 inhibitors | run_a22459de09d1 | Eg5 inhibitors (right) | 4/2/3/2 |
| s_2cdd0232ac | Epithelial | run_63bd7eb7b730 | Epithelial (right) | 4/1/2/2 |
| s_a5a83e59ab | Epithelial | run_669982512720 | Epithelial (right) | 4/1/3/2 |
| s_cedc34c90a | Epithelial | run_b045309793a1 | Epithelial (right) | 4/1/2/3 |
| s_01943ff958 | Kinase inhibitors | run_d2e7155e4ed5 | Kinase inhibitors (right) | 4/1/2/2 |
| s_14844eef0c | Kinase inhibitors | run_a55095da6468 | Kinase inhibitors (right) | 4/1/3/2 |
| s_3f70bdb6d1 | Kinase inhibitors | run_17dd486ad411 | Kinase inhibitors (right) | 4/1/2/2 |
| s_4329f72202 | Microtubule destabilizers | run_fc76b9455f97 | Microtubule destabilizers (right) | 4/1/3/2 |
| s_66b994c89e | Microtubule destabilizers | run_db499944f51a | Microtubule destabilizers (right) | 4/1/1/2 |
| s_93883f5fd7 | Microtubule destabilizers | run_f7b27ea537bc | Microtubule destabilizers (right) | 4/1/0/2 |
| s_bb3b52891e | Microtubule destabilizers | run_65896e65df6c | Microtubule destabilizers (right) | 4/1/1/3 |
| s_0ed866d71e | Microtubule stabilizers | run_b55b1185302a | Microtubule stabilizers (right) | 4/1/0/2 |
| s_89c9462717 | Microtubule stabilizers | run_5a6d74dd0d7d | Microtubule stabilizers (right) | 4/1/1/2 |
| s_f3007822f1 | Microtubule stabilizers | run_d55b09e6a606 | Microtubule stabilizers (right) | 4/1/0/2 |
| s_1ebd5529df | Protein degradation | run_0c4b62593623 | Protein degradation (right) | 4/1/2/2 |
| s_2e30d0950a | Protein degradation | run_b0c5cc504b34 | Microtubule stabilizers (wrong) | 4/1/2/2 |
| s_d4cbe87ca5 | Protein degradation | run_21b1c99002a4 | DNA replication (wrong) | 4/1/3/2 |
| s_e212dc8248 | Protein degradation | run_78b4db048064 | Protein degradation (right) | 4/2/2/2 |
| s_884ed608cb | Protein synthesis | run_269441e8496e | Protein synthesis (right) | 4/1/2/2 |
| s_dc9b1c73e4 | Protein synthesis | run_cce8b5ac20d5 | Protein synthesis (right) | 4/1/2/2 |
| s_fbe38ce784 | Protein synthesis | run_2a27b7279cd5 | Protein synthesis (right) | 4/1/2/2 |

The source Scientist's first call was right for 31/38 (with the atlas in view). Expect high with_nsc turn-1
accuracy, hence few compounds with correct-direction objections in that variant.

## 7. Evidence construction notes

- Wells are relabelled W1..W4 in acquisition order; well, field and image ids are dropped.
- Compound-name scan: every BBBC021 compound name (113, minus "DMSO" and "unknown", which BBBC021 lists as a
  compound but the Microscopist uses as a mechanism) is matched case-insensitively; 0 hits in the built evidence.
- `no_nsc` blocks are scanned for `atlas|NSC|neighbo(u)r|nearest|reference|similarity|1-NN`: 0 hits.
- `nsc_neighbours` / `nsc_moa_order` in `data/compounds.jsonl` are computed in code (see section 3, NSC check) and
  used only to pick misleading targets; they never enter a prompt.
