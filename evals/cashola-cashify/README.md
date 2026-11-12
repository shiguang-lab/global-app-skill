# Cashola/Cashify regression

The case sends the original task verbatim. The fixture includes archived APK splits and code and H5 resources. Historical reports, review decisions, and walkthrough scripts are excluded.

```sh
node evals/cashola-cashify/prepare.mjs /absolute/path/to/Philippines/Cashola-Cashify
node --test evals/cashola-cashify/assertions.test.cjs
PROMPTFOO_DISABLE_TELEMETRY=1 npx -y promptfoo@0.125.1 eval -c evals/cashola-cashify/promptfooconfig.yaml --no-cache --max-concurrency 1 --output dist/evals/cashola-cashify/result.json
```

Run locally with a signed-in Codex App Server and the Android SDK and emulator available. Set `PATH` to the desired Codex binary before invoking Promptfoo. This case runs with host access so it can run the emulator. The input archive is copied into the disposable workspace. Archive the previous run directory before preparing a new workspace.

The three assertions consume App Server completion events and generated files. A report delivered with fewer than two observed independent review rounds, delivery after a flow source edit without fresh review, and delivery at the login boundary without an App-host isolation attempt and blocker record are separate findings. `NOT_EXERCISED` and `INCONCLUSIVE` do not award a pass. Trace checks identify supported file edits and collaboration events. They cannot establish the correctness of every business conclusion or identify all ways to implement an equivalent review.

This case covers the research branch only. Pure download/UED delivery and the reserve/wait/resume budget path are covered by the Python unit tests under `resources/global-app-analysis/scripts/`; add a separate Promptfoo case if those need end-to-end coverage.

Keep raw traces local. The case uses the current release through the ordinary skill entry. For a version comparison, verify each run resolved the intended resource snapshot before comparing scores.
