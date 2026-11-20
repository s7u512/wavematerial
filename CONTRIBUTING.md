# Contributing to WaveMaterial

Thanks for your interest. WaveMaterial is a small hobby project, so these rules are short.
[`AGENTS.md`](AGENTS.md) holds the full rules; they apply to people as well as AI agents.

## Before you start

- For anything beyond a small fix, **open an issue first** so we can agree on the approach.
- Read [`docs/SPEC.md`](docs/SPEC.md). It lists what is decided for 1.0.0. Please don't
  reopen a decision without new information, and don't build features it lists as out of
  scope.

## Licence and sign-off

WaveMaterial is licensed **GPL-2.0-only WITH Universal-FOSS-exception-1.0**. By
contributing, you agree that your contribution is licensed under the same terms.

Every commit must be signed off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/). The sign-off
certifies that you wrote the change, or otherwise have the right to submit it under this
licence. Add it with `git commit -s`, which appends:

```
Signed-off-by: Your Name <your-email@example.com>
```

A GitHub no-reply address is fine.

## Making a change

- **One change per pull request**, touching nothing it doesn't need. A refactor goes in its
  own pull request.
- **Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):**
  `type(optional scope): summary`, where type is one of `feat`, `fix`, `docs`, `refactor`,
  `test`, `build`, `ci`, or `chore`.
- Every source file starts with
  `# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0`.
- Before you push, run the checks listed in `AGENTS.md` (`## This repository` › Checks), and
  say in the pull request which ones ran.
- A bug fix comes with a test that fails without it, unless the fix is obvious from reading.

## Dependencies and assets

- A new dependency must have an OSI-approved or FSF-free licence (never GPL-3.0, only or
  or-later, any AGPL, or proprietary), and is added to `THIRD_PARTY.md` in the same pull request.
- Icons, fonts, images, and sample audio must be your own work or under a licence recorded
  in `THIRD_PARTY.md`. Sample recordings and transcripts must be public domain.
- Never commit model weights, private recordings, personal data, secrets, or local paths.

## AI-assisted contributions

They're welcome. You are responsible for every line you submit: review it, test it, and
make sure it follows `AGENTS.md`.

## Security issues

Don't open a public issue. See [`SECURITY.md`](SECURITY.md).
