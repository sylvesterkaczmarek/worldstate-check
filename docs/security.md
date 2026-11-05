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
- HTTP transport errors report an error category instead of copying exception messages that may contain a request or redirect URL. The actual request URL is unchanged.
- Specifications are limited to 1 MiB.
- HTTP response bodies and JSON evidence are capped at 1 MiB by default.
- File text assertions are capped at 1 MiB by default.
- Telemetry JSON and CSV inputs are capped at 16 MiB by default. `max_read_bytes` can set a smaller or larger explicit limit.
- YAML duplicate keys and non-JSON-compatible YAML scalar types are rejected.
- HTTP JSON assertions, JSON files, and JSON telemetry reject duplicate keys and non-finite numbers. HTTP JSON assertions also require valid UTF-8.

These controls reduce accidental exposure and make reports safer to share. They do not make an untrusted specification safe to execute with `--allow-command`, `--allow-network`, or `--allow-outside-root`.

## Reliability candidate changes

The 0.2.0rc1 candidate requires boolean API permission flags, bounds normalized
specifications and parser depth, rejects unconsumed assertion parameters and uses
bounded regular-file observations. Reports cannot overwrite CLI specification or
local evidence inputs. Replacement of an existing report is atomic on the same
filesystem. An invalid or failed serialization preserves the old output.

Content paths reject special files and multiple hard links. Initial aliases are
resolved under the configured root, then POSIX descriptor-relative traversal
rejects later symlink replacement. Windows path checks are best effort under
concurrent changes. These controls are not an operating-system sandbox.

Verifier commands have closed stdin, monitored spool capture and bounded returned
bytes. POSIX-owned process groups are stopped on completion, timeout, overflow or
interruption. Windows descendant cleanup is best effort. Spool polling does not
establish a hard disk quota. See audit-2026-11-05.md for the full contract.
