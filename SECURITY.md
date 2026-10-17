# Security policy

## Supported versions

Only the latest `main` branch receives fixes. The v1 web app
(`backend/`, `frontend/`) is archived; reports about it are still welcome,
but fixes there are best effort.

## Reporting a vulnerability

Please report security problems **privately** through GitHub's private
vulnerability reporting:

- open the repository's **Security** tab and click **Report a
  vulnerability**, or go directly to
  <https://github.com/pennico/tts-ereader/security/advisories/new>.

Only the maintainer sees the report. Do not open a public issue, pull
request or discussion for a security problem. Include a description,
reproduction steps, and the impact if you can. You will get an
acknowledgement, and fixes are released as soon as practical.

## Scope notes

- The CLI tools run locally and only call the TTS/LLM APIs you configure.
  API keys live only in a local `.env` file that is gitignored. Never paste
  API keys into issues or code.
- The archived web app has no authentication and must not be exposed to the
  internet without a reverse proxy that adds it.
- `dispatcher/` runs the maintainer's AI agent sessions on a self-hosted
  machine. It acts only on issues, pull requests and comments from the
  maintainer and the repository's GitHub Actions bot, never on pull requests
  from forks. A way around that filter is in scope and worth reporting.
