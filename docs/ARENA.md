# Match testing

A pair consists of two games from the same starting position, with engine A playing side 0 in one game and side 1 in the other. The position's `first` field fixes the original first player. Both engines receive equal search time, CPU thread counts, and transposition table capacity. Executable SHA-256 hashes are saved in the configuration.

Repetition is recorded as a rematch under the game rules. The test scripts do not play that rematch: repetition and games unresolved at the ply limit each receive a test score of 0.5. This score does not represent an official draw. Report wins and losses alongside repetition and ply-limit counts.

Illegal moves, abnormal exits, and unresponsive games are saved as failures, and their entire pair is excluded from strength statistics. Report failures and the planned pair count together. Do not accept a candidate while a trial has failures. Save both internal search time and externally measured elapsed time so that host scheduling delays can be inspected.

Keep candidate evaluation positions separate from tuning positions, and fix the pair count and configuration before starting. Report a bootstrap 95% interval over pair means. A candidate that improves in an initial 100-pair trial is checked on a separate 500-pair trial under the same conditions. A 100-pair interval that touches 50% may also justify confirmation. Accept a candidate only when every planned pair is complete and the confirmation interval's lower bound exceeds 50%. `--confirmation` requires at least 500 pairs and records the trial as a confirmation run. Small trials check integration and regressions; they do not establish that an engine is the strongest.

Results are finalized as JSON one pair at a time. After interruption, rerun unfinished pairs with the same configuration. Completed pairs with game records are not counted twice. Use a new output directory if the configuration or executable changes.

The default concurrency is three games. The upper limit is the smaller of six and the logical CPU count minus two, with a minimum of one. Concurrency can change during a trial while preserving completed pairs. Keep each engine's search time, thread count, and transposition table capacity unchanged, and record the reason and throughput in the experiment log. Elapsed time includes contention from other host processes.

Reconstruct fixed benchmark positions, including repetition history, from tuning game records. This example runs basic search, PVS, and NNUE search for 200 ms each on six positions, checking move legality and that search leaves the position unchanged.

```bash
.venv/bin/python scripts/bench_search.py \
  --game artifacts/selfplay/pair-00000.json \
  --engine build/kokoriko \
  --model models/example/model-int.nnue --ms 200 \
  --out artifacts/search-speed.json
```

PVS is the default. Use `--basic-a` or `--basic-b` to compare basic search. `--tuned-a` / `--tuned-b` explicitly select PVS. The comparison record saves executable SHA-256 hashes and selected arguments.

Use `--selective-a` / `--selective-b` to compare selective search. This mode includes PVS and cannot be combined with `--basic-*` / `--tuned-*` for the same side.
