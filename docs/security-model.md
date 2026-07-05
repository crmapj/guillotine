# Security Model

Guillotine has two security surfaces:

1. the generated DSL that calls an external API, and
2. the runtime that may execute agent-authored Python code against that DSL.

## Current Boundary

The current runtime uses a short-lived local Python subprocess. It is suitable for
local development and proof-of-concept MCP integration. It is not a hardened
multi-tenant sandbox.

The generated proof-of-concept MCP wrapper deliberately does not accept API tokens as
tool arguments. Passing a secret into the current subprocess environment would make it
readable to arbitrary agent-authored Python code.

For hosted or untrusted execution, replace `guillotine.runtime.execute` with a stronger
executor while preserving the result contract:

- container or microVM isolation,
- deny ambient network except through the generated DSL,
- inject secrets outside model context,
- capture stdout/stderr separately from returned data,
- cap time, memory, output size, and filesystem access.

## Secrets

Do not put secrets in prompts, generated skills, examples, or bug reports. Generated
clients accept credentials through explicit arguments and environment variables for
trusted local scripts. For untrusted or hosted code execution, keep secrets in a
supervisor outside the subprocess and replace the executor with an adapter that can
call the API without exposing credentials to user code.

## Generated Code Review

Before using a generated DSL with a sensitive API:

- run `guillotine inspect`,
- review destructive operations,
- compile generated code,
- run a read-only smoke,
- run write/delete tests against a disposable account or sandbox.
