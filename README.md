# searchdrift

An open, continuously running benchmark for MCP (Model Context Protocol) server
quality and agent readiness.

The benchmark runs open-source MCP servers in isolated Docker containers and measures:

- **Protocol conformance** — correct MCP/JSON-RPC implementation
- **Robustness** — behavior under malformed input, fuzzing, crashes
- **Performance** — cold start, latency percentiles, throughput, resource usage
- **Agent-readiness** — static analysis of tool descriptions and schemas
- **Breaking changes** — schema diffs across server releases
- **Agent behavior** — Gemini-powered tool selection and task completion experiments,
  verified by deterministic end-state checks (never an LLM judge)

The deterministic benchmark is the core and never depends on an LLM.
Model-powered experiments are modular and run on the Gemini API free tier
with quota management and full record/replay.

## Layout

```
searchdrift/  Python package: MCP client, server runner, SQLite-backed storage
analysis/     statistical analysis and visualizations
```

## Status

Early development — Phase 1 (MCP client and execution harness). See the roadmap
in the project plan.

## Security

All third-party MCP servers run in containers with no network access, CPU/memory
limits, execution timeouts, and no host mounts. API keys never enter a sandbox.
Tool outputs are treated as untrusted data.
