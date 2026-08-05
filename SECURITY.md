# Security Policy

## Supported Versions

Only the latest release is supported. Security fixes land on `dev` (the default
branch) and go out in the next tagged release; older tags are not patched.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, report it privately using one of these channels:

1. **Preferred:** Use GitHub's [private vulnerability reporting](../../security/advisories/new)
   for this repository (Security tab → "Report a vulnerability").
2. **Alternative:** Email hkyss.services@protonmail.com with a description of
   the issue, steps to reproduce, and its potential impact.

You should expect an initial response within 7 days. If the report is
confirmed, a fix will be prepared and a GitHub Security Advisory published
once a patch is available. Please allow a reasonable amount of time for a
fix to be released before any public disclosure.

## Scope

`devctl` orchestrates local Docker Compose stacks and a local reverse proxy
for development use. Reports involving the CLI, the container image build,
generated Compose/Caddy configuration, or the port-allocation/state logic
are in scope. Vulnerabilities in third-party dependencies should be reported
upstream as well as here if `devctl`'s usage of them is affected.
