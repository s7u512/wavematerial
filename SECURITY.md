# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub:
**Security › Report a vulnerability** on this repository. Don't open a public issue, and
don't post exploit details, proof-of-concept code, or malicious files publicly until a fix
is out.

Include the WaveMaterial version, your operating system, what an attacker could do, and
the steps to reproduce. Remove personal paths, private recordings, and secrets from any
logs you attach.

This is a hobby project maintained in spare time, so replies may take a few days. You will
get an acknowledgement, and a fix or an explanation once the report has been looked at.

## Supported versions

Only the latest release gets security fixes.

## Scope

In scope:
- The local web server: it binds to `127.0.0.1` with a per-launch token, so another local
  program or a web page driving it without the token is a vulnerability.
- Opening media files: decoding untrusted audio or video, and file and path handling
  (path traversal, unsafe overwrites).
- Model downloads: anything that lets a file that fails its pinned sha256 check be used.
- The update check, and the integrity of release installers.
- The transcript editor and outputs: script injection through transcript text.

Out of scope: problems that need an attacker who can already run code as your user, and
bugs with no security impact (please use a normal issue for those).
