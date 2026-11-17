# Pi Model Evaluation Summary

## Scope and interpretation

Three harnesses were attempted across the six configured model endpoints. Runs were bounded to 15 shared promptfoo tasks per model, 30 ARC-Challenge test questions per model in EvalScope, and a 15-pair Orq Arena tournament with one prompt per pairing. Results are provider/endpoint observations from this run, not general claims about underlying model families. No credential values are included in configs or reports. Promptfoo writes provider-key metadata as the literal `[REDACTED]` placeholder in its aborted raw result; this is not a credential.

Direct calls to the configured endpoints matter here: both Xingchi models returned HTTP 403 (`client_not_allowed`) stating that scripted/SDK clients are unsupported; Howtofix returned HTTP 429/503 and did not yield a completed sample; those are availability/policy outcomes, not model-quality scores. We did not spoof a permitted client. The local OpenAI-compatible adapter is at `http://127.0.0.1:18765/v1`; it routes provider calls using environment credentials in memory and logs only model label, status, latency, and error type. Port 8765 was occupied by an unrelated pre-existing process, so the adapter was moved. Raw artifacts and intermediate failures are retained alongside final outputs.

## 1. Promptfoo

15 shared coding, reasoning, factual QA, instruction-following, and summarization prompts; custom deterministic checks; `showThinking=false` for final-answer grading. Runs were independent per provider to prevent one endpoint error from aborting other models. Promptfoo reported completion/error status as follows:

| Model | Passed | Failed checks | Errors | Interpretation |
|---|---:|---:|---:|---|
| `xingchi/gpt-6-astra` | 0 | 0 | 1 | Fail-fast on HTTP 403; no prompt scored |
| `xingchi/gpt-6.1-sol` | 0 | 0 | 1 | Fail-fast on HTTP 403; no prompt scored |
| `tokenlab/DeepSeek-V4.1-Flash` | n/a | n/a | n/a | Run exceeded 300-second cap; partial console log retained, no final aggregate |
| `moss/nex-n2.6` | 15 | 0 | 0 | 100% of these checks passed |
| `howtofix/deepSeek-v4.1-flash-1017-sg` | 0 | 0 | 15 | Every prompt returned HTTP 503 |
| `100milionseek/deepseek-v4.1-flash-free` | 13 | 1 | 1 | 13/14 answered prompts passed; one word-count format miss, one HTTP 503 |

These intentionally strict checks are screening signals, not a validated benchmark. Models may have emitted hidden reasoning that promptfoo normally prepends to output; the final runs disable that behavior before grading. See `promptfoo-*-results.json` and logs. The partial TokenLab run is in `promptfoo-tokenlab__DeepSeek-V4.1-Flash-results.json`; the capped retry log is `promptfoo-tokenlab-final.log`.

## 2. EvalScope: ARC-Challenge

30 zero-shot ARC-Challenge test questions per configured endpoint. Accuracy is correct answers divided by 30. The challenge subset and seed 42 were held constant.

| Model | Accuracy | Correct / attempted | Mean latency (s) | Output tok/s | Status |
|---|---:|---:|---:|---:|---|
| `xingchi/gpt-6-astra` | n/a | 0 / 30 | n/a | n/a | 30 HTTP 403 errors |
| `xingchi/gpt-6.1-sol` | n/a | 0 / 30 | n/a | n/a | 30 HTTP 403 errors |
| `tokenlab/DeepSeek-V4.1-Flash` | 93.3% | 28 / 30 | 11.54 | 0.70 | Complete |
| `moss/nex-n2.6` | 76.7% | 23 / 30 | 4.20 | 21.59 | Complete |
| `howtofix/deepSeek-v4.1-flash-1017-sg` | n/a | 0 / 30 | n/a | n/a | 30 errors, primarily 429/503 |
| `100milionseek/deepseek-v4.1-flash-free` | 90.0% | 27 / 30 | 30.58 | 1.57 | Complete |

Latency and generation throughput are EvalScope aggregates for this run and include provider/network effects. Small sample size means close scores should not be treated as statistically decisive. Raw reports are under `evalscope/<model>/reports/`; prediction/review JSONL and logs are retained per model.

## 3. Orq Arena

The actual Orq Arena CLI ran 15 round-robin pairings, one seeded prompt per pairing. Orq requires `ORQ_API_KEY`; no such credential was configured. To preserve a real CLI run without misrepresenting a dummy credential as Orq access, the run used a local adapter and a placeholder process value only to pass the CLI's presence check. Candidate and judge calls still route to their configured providers. `xingchi/gpt-6.1-sol` was configured as the sole judge via a `judge/sol` adapter alias, including when Sol is itself a candidate; this overlap is disclosed and is not neutral.

| Arena outcome | Value |
|---|---:|
| Pairings attempted | 15 |
| Rated rounds | 0 |
| Voided rounds | 12 |
| Inconclusive rounds | 3 |
| Usable final ranking | No |

Judge requests were rejected with HTTP 403, while several candidate calls also failed (403 or 429). The CLI emitted an all-1000 default Elo table, but explicitly exited with “no round was rated”; those numbers are not a result and are excluded. See `arena-adapter-run.log`, `battles.jsonl`, and `battles.report.html`.

## Overall ranking (1–6)

This is a practical ordering of the evidence available, not a six-way model-quality leaderboard. Models with completed ARC scores rank first; promptfoo is a limited tie-break signal. Endpoints with no usable quality measurement are ordered after them by availability evidence, with ties acknowledged.

| Rank | Model | Reason |
|---:|---|---|
| 1 | `tokenlab/DeepSeek-V4.1-Flash` | Highest completed ARC result (28/30, 93.3%); promptfoo aggregate unavailable due to the 300-second cap. |
| 2 | `100milionseek/deepseek-v4.1-flash-free` | 27/30 ARC (90.0%) and 13/14 answered promptfoo checks passed; one transient 503 and one formatting miss. |
| 3 | `moss/nex-n2.6` | 23/30 ARC (76.7%) but passed all 15 promptfoo checks; fastest mean ARC response of the three measured endpoints. |
| 4 | `howtofix/deepSeek-v4.1-flash-1017-sg` | No quality score: all ARC items errored and all promptfoo tasks returned 503; poor observed availability. |
| 5 | `xingchi/gpt-6-astra` | No quality score: scripted harness calls were explicitly rejected with HTTP 403. |
| 6 | `xingchi/gpt-6.1-sol` | Same 403 access restriction; also unavailable as Orq judge, preventing all arena judgments. Placed after Astra only as a reporting tie-break, not a quality distinction. |

Ranks 4–6 are not quality comparisons; the available evidence only distinguishes observed service failures and their impact on the requested workflows. The Orq Arena did not produce a ranking.

## Pi-way follow-up (headless Pi 1.5.2)

The original direct results above remain historical. The follow-up calls the real Pi CLI for each item: `pi --no-session --no-tools --no-mcp --no-extensions --no-skills --no-prompt-templates --no-context-files --model <provider/model> -p -- <original prompt>`. Every Xingchi request in this follow-up goes through Pi; no direct HTTP/SDK calls, adapter, model substitution, or client impersonation are used.

The 15 prompt texts come from `promptfoo.config.json`. The 30 fully rendered ARC inputs and target keys come from the existing EvalScope prediction/review files, joined by sample index (review file line order differs from index order). All texts and targets were checked against the original artifacts, including the direct Moss control. `pi-way/manifest.json` records source SHA-256 hashes. Each item uses a fresh session, a 150-second process timeout, and separate raw stdout/metadata files. Completed items from the interrupted run were resumed without rerunning them.

Promptfoo answers are graded by the original `assertions.cjs`, invoked unchanged. ARC answers use the installed EvalScope `parse_answers` extractor and original target letters. Errors are excluded from quality accuracy and reported separately.

| Model | Promptfoo checks | ARC-Challenge | Call errors | Status |
|---|---:|---:|---:|---|
| `xingchi/gpt-6-astra` | n/a (0 answered) | n/a (0 answered) | 45/45 | Pi reached the provider, which returned HTTP 404 `model_not_found`: no configured account in the group supports `gpt-6-astra`. |
| `xingchi/gpt-6.1-sol` | 15/15 (100%) | 30/30 (100%) | 0/45 | Completed through Pi. |
| `moss/nex-n2.6` control | 15/15 (100%) | 30/30 (100%) | 0/45 | Completed; direct comparison was 15/15 promptfoo and 23/30 ARC. |

Sol's mean process wall time was 35.37 seconds per promptfoo item and 12.30 seconds per ARC item; Moss's was 6.51 and 6.68 seconds respectively, including CLI startup and Pi processing. These are different measurements from EvalScope request latency. Moss matches its direct promptfoo score but improves from 23/30 to 30/30 on ARC. This control supports matching checks on the simple prompt suite while showing that the client configurations can produce materially different ARC outcomes; Sol's Pi score should not be inserted unqualified into a direct-client leaderboard.

The follow-up holds item text, answer keys, and grading constant, but changes the calling environment: Pi adds its default coding-agent system prompt and uses its configured generation settings; this run does not override temperature, reasoning, or output-token limits to match the original direct runs (temperature 0, 768 promptfoo / 128 ARC output tokens). Tools and external context are disabled. Scores therefore compare performance on identical items under two client configurations; they are not a controlled measurement of client routing alone. Thirty ARC questions and simple heuristic promptfoo assertions provide limited evidence; Python/SQL checks do not execute generated code. The 30/30 result does not establish superiority on the full ARC dataset. Orq was not rerun, and its original zero-rated-round outcome remains unchanged.

See `pi-way/scores.json`, per-model `*-graded.json`, and `pi-way/raw/<provider>__<model>/` for scores, answers, exit status, and timing. The original ranking above predates this follow-up and is superseded for Sol's availability/quality evidence: Sol and Moss tie on both Pi-way suites, while Astra remains unmeasured rather than receiving a zero quality score. There is no defensible new strict six-way ranking combining these differing client conditions. Final artifact audit found no environment credential values in the follow-up files.

## New-key Pi-way retest (2026-11-17 rotation, user-reported)

Both Xingchi models were rerun as 45 fresh Pi CLI calls each, under the environment containing the rotated `XINGCHI_API_KEY` (the secret value was neither printed nor saved). The method and grading are unchanged from the Pi-way follow-up above; the 15 prompts, 30 ARC items/targets, assertions, and EvalScope answer extractor were reused. New artifacts are isolated in `pi-way/raw-newkey/`, `*-graded-newkey.json`, `scores-newkey.json`, and `manifest-newkey.json`; old-key records remain unchanged.

| Model | Promptfoo checks | ARC-Challenge | Errors / timeouts | Comparison with old-key Pi-way |
|---|---:|---:|---:|---|
| `xingchi/gpt-6-astra` | n/a (0 answered) | n/a (0 answered) | 45/45 provider 503 | Old-key run was also unscored (45 provider 404s); the new key did not yield an answer in this run. |
| `xingchi/gpt-6.1-sol` | 14/15 (one six-word format check failed) | 27/29 answered (two wrong), one timeout | 1/45 timeout | Old-key run scored 15/15 and 30/30 with no call errors. The new-key score was lower on both sets; ARC has one unanswered item excluded from accuracy. |

Astra's stderr consistently reported HTTP 503 `Service temporarily unavailable`, not an answer or a scoring failure. Sol's only call failure was ARC item 3 timing out at the 150-second per-call cap. Its two incorrect ARC items were indices 4 and 5; both are included in 27/29. Promptfoo's miss was the word-count task. Timing and score differences are observations from one small run and do not establish that key rotation caused a quality change. Provider load, nondeterminism, and Pi generation defaults may contribute. There was no direct API retry or alternate client path.

See `pi-way/scores-newkey.json` and `pi-way/*-graded-newkey.json` for totals; per-call stdout, exit codes, durations and sanitized error text are in `pi-way/raw-newkey/`. The new-key manifest records source hashes and methodology without storing key material.

## Reproducibility and artifact map

- `models.public.json`: model IDs, base URLs, and environment variable names only.
- `promptfoo.config.json`, `assertions.cjs`, `promptfoo-*-results.json`: prompt suite/config and raw result databases.
- `evalscope-*.json`, `evalscope/*/`: bounded EvalScope configs, reports, predictions, and logs.
- `arena.config.json`, `arena.prompts.jsonl`, `router.py`, `arena-adapter-run.log`, `battles.jsonl`, `battles.report.html`: arena config, prompts, local router and output.
- `PROGRESS.md`: run notes and status.

The workspace is not a Git repository, so no commits were possible. No external research results were used in scoring.