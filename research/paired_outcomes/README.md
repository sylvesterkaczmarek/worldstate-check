# Paired outcomes pilot v1

A deployment accepts a rollout while an old worker still answers the canary. A gripper releases an object that initially appears in place and then slips. This pilot asks what an observer can conclude from acknowledgements, snapshots, target identity and later measurements.

There are 66 constructed episodes across six families, with 22 development episodes and 44 held-out episodes. Each is scored under four evidence views by five methods (1,320 decisions). The reference scorer reads the worker's request log or the high-rate MuJoCo position and contact data. Evaluated methods see only the exposed observation file. Input budgets and views are identical across methods. Agent text and scenario names are excluded from the verifier. Every case acknowledges the action, so acknowledgement-only is a deliberately weak control.

## Held-out results with all available samples

| Domain | Method | Failed outcomes accepted | Genuine successes accepted | Uncertain among failures / successes |
| --- | --- | --- | --- | --- |
| Deployment | 0.2-compatible snapshot | 10/12 | 10/10 | 0 / 0 |
| Deployment | WorldState Check | 2/12 | 6/10 | 6 / 4 |
| Deployment | Hand-written temporal checker | 2/12 | 6/10 | 6 / 4 |
| Placement | 0.2-compatible snapshot | 8/10 | 12/12 | 0 / 0 |
| Placement | WorldState Check | 0/10 | 6/12 | 4 / 6 |
| Placement | Hand-written temporal checker | 0/10 | 6/12 | 4 / 6 |

Both deployment misses were a canary failure between samples. Missing or duplicated observations cost genuine successes in both domains. Acceptance of successful episodes fell by 40 and 50 percentage points, respectively, exceeding the pilot's five-point allowance. The equally informed hand-written checker agreed with WorldState Check. These results measure constructed failure mechanisms. The two held-out families per domain share scenario templates, making the family bootstrap intervals descriptive only. The data do not establish deployment prevalence, benefits for a particular agent, or a physical robot's reliability.

## Reproduce

From a source checkout, install with `python -m pip install .`. The first command recomputes every decision, denominator and paired interval from the recorded episodes. It needs no simulator, service or model. The second verifies the frozen artifact hashes.

```bash
python research/paired_outcomes/analyze.py --out results.local.json --timings timings.local.json
python research/paired_outcomes/verify_archive.py results.local.json
```

To regenerate acquisitions, install `python -m pip install '.[simulator]'` and run `python research/paired_outcomes/record.py --out episodes.local.json`. This starts disposable loopback HTTP workers and headless MuJoCo simulations. Source clocks in the deployment trace are scheduled logical request ticks. Physics runs at 5 ms per step. The compact visible view retains three scheduled samples over one second when available. Platform-level variations in physics may change recorded bytes. Compare labels, decisions and source versions as well as digests.

The root MIT licence covers the code and the generated traces. The archive manifest pins the protocol, data, reference scorer, collectors, analysis and results. Citation metadata is in the repository's CITATION.cff. The development and held-out families are all public in this release. An independent confirmatory study needs newly held-out cases, independently authored labels and a larger number of independent families. [Protocol](protocol.md) · [Per-episode decisions and aggregate tables](results.json)

The archived timings.json contains the Linux/Python 3.12 pilot timings by split, domain, view and method. To cross-check the historical baseline, run `python research/paired_outcomes/check_legacy.py` in an environment containing exactly worldstate-check 0.2.0. All 264 historical decisions matched in the release check.

The optional timings measure wall time per scoring call. WorldState Check and the snapshot rule parse a local evidence file, while the hand-written baselines consume the same view already in memory. Evidence preparation and source collection are outside those measurements.
