# WorldState Check 0.3.0

Released 21 November 2026 under the MIT licence. This version evaluates declared postconditions against recorded observations and reproduces the verdict offline.

## What changed

HTTP predicates can share a response across checks. The sampled-window check binds observations to a subject and interval, identifies the first failing sample and reports incomplete evidence. The optional Inspect AI scorer keeps all three verdicts. See the [migration and replay guide](https://github.com/sylvesterkaczmarek/worldstate-check/blob/v0.3.0/docs/observation-replay.md).

Install and replay the bundled robot placement:

```sh
python -m pip install worldstate-check==0.3.0
worldstate-check replay --example placement
```

The first failing sample is 100 at 0.5 seconds. The command returns `NOT_VERIFIED` with exit code 1.

## Research materials

The release includes the protocol, 66 labelled episodes, reference scorer, baseline implementations, all 1,320 decisions, timing data and a checksum manifest. On the held-out families, the sampled-window verifier accepted fewer failed outcomes and fewer genuine successes than the snapshot baseline. The equally informed hand-written checker matched its decisions. [Pilot results and reproduction instructions](https://github.com/sylvesterkaczmarek/worldstate-check/tree/v0.3.0/research/paired_outcomes).

## Citation

Kaczmarek, S. (2026). *WorldState Check* (version 0.3.0) [Computer software]. [GitHub release](https://github.com/sylvesterkaczmarek/worldstate-check/releases/tag/v0.3.0).
