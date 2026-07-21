# Third-Party Notices

DebMirror Manager's own source code is licensed under the Apache License 2.0 (`Apache-2.0`); see `LICENSE`.

This file summarizes the principal third-party software used directly by the project. It is not a replacement for the copyright and license files distributed by each dependency or operating-system package.

## Python runtime dependencies

| Component | Version | License |
| --- | ---: | --- |
| Flask | 3.1.3 | BSD-3-Clause |
| Werkzeug | 3.1.8 | BSD-3-Clause |
| cryptography | 49.0.0 | Apache-2.0 OR BSD-3-Clause |
| Gunicorn | 26.0.0 | MIT |
| Jinja | locked transitive version | BSD-3-Clause |
| Click | locked transitive version | BSD-3-Clause |
| itsdangerous | locked transitive version | BSD-3-Clause |
| MarkupSafe | locked transitive version | BSD-3-Clause |
| blinker | locked transitive version | MIT |
| cffi | locked transitive version | MIT |
| pycparser | locked transitive version | BSD-3-Clause |
| packaging | locked transitive version | Apache-2.0 OR BSD-2-Clause |

Exact resolved versions and hashes are recorded in `requirements.lock`. Upstream license files remain part of the installed Python distributions.

## Container base images

- The application image is based on the Docker Official Image for Python 3.12 on Debian Bookworm. Python is distributed under the Python Software Foundation License; Debian packages retain their individual licenses.
- The optional mirror HTTP service uses the Docker Official Image for nginx on Alpine Linux. nginx and Alpine packages retain their individual licenses.

The Docker image references are pinned in `Dockerfile` and `docker-compose.yml`. Their digests identify the exact multi-platform image indexes used for this release.

## Debian packages installed in the application image

The application image installs Debian packages including `debmirror`, GnuPG, `gpgv`, `rsync`, OpenSSH client, `lftp`, `curl`, compression tools, and supporting utilities.

`debmirror` is distributed under **GPL-2.0-or-later**. The WebUI invokes it as a separate program and does not incorporate its source code.

For a built container, authoritative package notices are available under `/usr/share/doc/<package>/copyright`. Distributors of modified or repackaged container images must preserve the applicable notices and provide corresponding source where an included license requires it.

## No vendored frontend framework

The current source archive does not vendor Bootstrap, Bootstrap Icons, or another external JavaScript/CSS framework. The files under `app/static/` are project assets unless their headers state otherwise.

## Trademarks and affiliation

DebMirror Manager is an independent third-party community project. It is not affiliated with, endorsed by, or maintained by the Debian Project or the maintainers of `debmirror`. Debian and other product names are trademarks of their respective owners.
