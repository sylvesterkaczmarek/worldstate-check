# Security

WorldState Check evaluates local specifications that may reference files, network endpoints, or commands. Treat task specifications from untrusted sources as untrusted code-adjacent input.

By default, file paths are restricted to the verification root and command checks are disabled. Use `--allow-outside-root` or `--allow-command` only for specifications you trust.

To report a security issue, use GitHub's private vulnerability reporting if enabled, or contact the repository owner privately rather than opening a public exploit report.
