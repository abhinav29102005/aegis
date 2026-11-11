## Summary

<!-- Describe what this PR changes and which module(s) it touches. -->

## Checklist

- [ ] Shared contracts in `packages/contracts/` remain consistent (or schemas regenerated)
- [ ] No hardcoded secrets or credentials
- [ ] Deterministic policy engine / financial invariants preserved (LLMs never authorize or capture payments)
- [ ] Tenant isolation verified
- [ ] Backend tests pass (`uv run pytest`)
- [ ] Frontend typecheck & lint pass (`npm run typecheck && npm run lint`)

