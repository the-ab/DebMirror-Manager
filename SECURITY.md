# Security Policy

## Supported versions

Only the latest published DebMirror Manager release receives security fixes. Older releases may contain known vulnerabilities and should be upgraded before a report is investigated.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Older releases | No |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting or a private Security Advisory for the repository. Do not disclose exploitable details in a public issue, discussion, pull request, or forum post.

When private reporting is not available, open a public issue containing only a request for a private security contact. Do not include credentials, private keys, production data, access tokens, or proof-of-concept code in that issue.

Include, where possible:

- affected version and installation method;
- attack prerequisites and affected role;
- exact request, input, or workflow that triggers the issue;
- impact and whether production data was accessed;
- a minimal reproduction using non-sensitive test data;
- any suggested mitigation.

## Coordinated disclosure

Reports are reviewed on a best-effort basis. The maintainer will validate the issue, prepare a fix, and coordinate a disclosure date appropriate to the severity. Please allow time for users to update before publishing technical details.

## Security boundaries

DebMirror Manager executes administrator-approved mirror jobs and user scripts inside its container. Administrators therefore have intentionally broad control over mounted mirror and application data. The container must not be exposed directly to untrusted networks and must not be granted the Docker socket or privileged mode.

Security-sensitive deployment guidance is maintained in `README.md` and `README.de.md`.
