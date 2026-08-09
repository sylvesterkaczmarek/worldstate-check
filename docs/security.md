# Security model

A verification specification can direct WorldState Check to read files, contact network endpoints, or, when explicitly enabled, run commands.

## Default boundaries

- File and telemetry paths are restricted to the verification root.
- `..` paths that escape the root become `UNKNOWN` rather than being read.
- Command checks are disabled unless `--allow-command` is supplied.
- Command checks use an argument vector and `shell=False`.
- Command checks receive only `PATH` and `HOME` from the parent environment.
- HTTP response bodies used as evidence are capped at 1 MiB.
- File text assertions are capped at 1 MiB by default.

These controls reduce accidental exposure. They do not make an untrusted specification safe to execute with `--allow-command` or `--allow-outside-root`.
