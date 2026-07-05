# Security Policy

Guillotine generates code that calls external APIs. Treat generated DSLs as capability
surfaces and review them before using them in sensitive automation.

## Current Runtime Boundary

The v0 runtime uses a short-lived local Python subprocess. It is suitable for local
development and MCP proof-of-concept use, but it is not a hardened multi-tenant
sandbox. Hosted deployments should replace `guillotine.runtime.execute` with a stronger
executor such as a locked-down container, microVM, gVisor, or equivalent sandbox while
keeping the same result contract.

The generated proof-of-concept MCP wrapper does not accept API tokens as tool
arguments. Do not pass authenticated secrets into the current subprocess executor for
untrusted code; arbitrary Python can inspect its environment.

## Secrets

Generated DSLs accept credentials through explicit arguments or environment variables.
Do not paste API tokens into prompts or generated skills. Prefer host-managed secrets
and a hardened supervisor that keeps credentials outside agent-authored code.

## Reporting

Use GitHub private security advisories for vulnerability reports. If you cannot use
GitHub advisories, contact the maintainers privately instead of opening a public issue.

Include reproduction steps, the generated API surface, the OpenAPI operation involved,
and whether the issue affects generated code, the runtime executor, or both.
