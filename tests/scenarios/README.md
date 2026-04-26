# Scenario Tests (NOT in regression suite)

These tests cover **specific business scenarios** — usually a particular
employee + plan-template combination — and are deliberately kept out of the
default regression suite so that:

- Adding/changing a FAQ doesn't ripple into broken regression tests.
- The regression suite stays under ~2min so it can run on every PR.

## When to run

- **Manual**: when developing or debugging a specific scenario.
- **Pre-release**: as part of major version validation, alongside the
  regression suite.
- **After a planning / template change**: to verify the affected scenario.

## How to run

```bash
# Just scenarios:
pytest tests/scenarios -m scenario

# Specific employee:
pytest tests/scenarios/test_json_template_execution.py -k throughput

# Together with the regression suite (release validation):
pytest
```

## What's here

- `test_json_template_execution.py` — full execute_plan path against
  respx-mocked APIs + Mock LLM, per-template assertions.
- `test_json_template_execution_by_mock_llm.py` — same but Mock LLM only,
  no API mocking (planning / decision logic focus).

## Adding new scenario tests

Use `@pytest.mark.scenario`. Do **not** add `@pytest.mark.contract` /
`health` / `smoke` to anything in this folder — those are reserved for the
regression suite.
