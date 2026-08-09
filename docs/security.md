# Security model

A verification specification can direct WorldState Check to read local evidence and, only when explicitly enabled, contact network endpoints or run commands. Treat specifications from untrusted sources as untrusted code-adjacent input.

## Default boundaries

- File, JSON, and telemetry paths are restricted to the verification root.
- `..` paths and symlink targets that resolve outside the root become `UNKNOWN` rather than being read.
- Command checks are disabled unless `--allow-command` is supplied.
- HTTP and TCP checks are disabled unless `--allow-network` is supplied.
- Commands use an argument vector with `shell=False` and receive a minimal environment.
- Raw command arguments and command output are not copied into evidence reports. Reports record the executable, argument count, byte counts, and output hashes.
- HTTP report evidence removes URL credentials, query strings, and fragments.
- Specifications are limited to 1 MiB.
- HTTP response bodies and JSON evidence are capped at 1 MiB by default.
- File text assertions are capped at 1 MiB by default.
- Telemetry JSON and CSV inputs are capped at 16 MiB by default. `max_read_bytes` can set a smaller or larger explicit limit.
- YAML duplicate keys and non-JSON-compatible YAML scalar types are rejected.

These controls reduce accidental exposure and make reports safer to share. They do not make an untrusted specification safe to execute with `--allow-command`, `--allow-network`, or `--allow-outside-root`.
