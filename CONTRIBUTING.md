# Contributing

Contributions are welcome when they keep the verifier small, deterministic, and inspectable.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install pytest
pytest
```

New check types should include success, failure, malformed-input, and boundary tests. Avoid adding an LLM dependency to core verdict logic.
