# LLM Response Cache

JSON files of recorded LLM (prompt, response) pairs. Committed to git so
the test suite is deterministic and runs without LLM API access.

## How it works

The `recorded_llm` fixture in `tests/conftest.py` patches both LLM
entry points the codebase uses:
- `backend.agent.graph.build_llm()` → wrapped by `RecordedLangChainLLM`
- `backend.tools._llm.invoke_llm()` → wrapped by `RecordedInvokeLLM`

Each call hashes the (model + temperature + system + user prompt) — after
normalizing date/UUID/timestamp drift — into a stable key. Cache files
land under `langchain/<shard>/<key>.json` or `invoke_llm/<shard>/<key>.json`.

## CLI modes

```bash
# Default — replay only; cache miss → CacheMissError
pytest

# Record any new prompts (most common after adding/modifying a test)
pytest --llm-mode=record-missing

# Force-overwrite all cache (after model upgrade or major prompt rewrite)
pytest --llm-mode=record-all

# Hit real LLM, do NOT touch cache (for drift detection)
pytest --llm-mode=passthrough
```

## When to refresh

| Situation | Mode | Notes |
|---|---|---|
| Added a new test using `recorded_llm` | `record-missing` | Generates new entries only |
| Modified a prompt template (perception/planning/reflection) | `record-missing` | Old entries become unreachable; new ones recorded |
| Major model upgrade (e.g. qwen3 → qwen4) | `record-all` | Review diffs carefully before commit |
| Suspected prompt drift (LLM output changed?) | `passthrough` | Compare against existing cache, no overwrite |

## API key requirement

Recording modes need one of:
- `QWEN_API_KEY` (preferred, matches production model)
- `OPENAI_API_KEY`
- `DEEPSEEK_R1_API_KEY`

Replay mode needs **no key** — that's the point.

## Cache hygiene

- Cache file size: typically < 50KB each. 50 tests ≈ 2.5 MB total.
- Sharded by first 2 chars of the hash; no single dir ever has > ~500 files.
- Safe to delete and re-record — keys are stable across runs.

## Drift detection (advanced)

Run nightly against a real LLM and diff against the replayed run:
```bash
pytest tests/health -m health --llm-mode=passthrough -v > /tmp/passthrough.log
pytest tests/health -m health -v > /tmp/replay.log
diff /tmp/passthrough.log /tmp/replay.log
```

Significant divergence ⇒ prompts behave differently from cache; refresh
or investigate.
