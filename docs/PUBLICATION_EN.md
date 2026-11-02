# Prepare a GitHub publication

[Українська](PUBLICATION_UK.md) · [English](PUBLICATION_EN.md)

Publish only this sanitized source root, never the surrounding working
installation. Start a new Git history for the first public release.

1. Read the validation report and run source audit/host tests.
2. Review every staged file, including hidden files. `.gitignore` does not remove
   data already tracked by Git.
3. Configure your chosen public Git name and GitHub noreply email locally.
   This repository does not select a personal commit identity for you.
4. Initialize Git here, inspect `git diff --cached --stat` and
   `git diff --cached`, then commit only reviewed files.
5. Create your repository and configure its remote URL. No personal GitHub
   username/remote is embedded. Push is a separate explicit owner action.
6. Upload APK/ZIP assets to a release rather than committing binaries into source
   history. Include beta status, platform, signature status, checksums and limits
   of acceptance. Never upload keystores/passwords.
7. Enable available secret-scanning protection and inspect alerts. This supplements
   local review but cannot know every private IP or arbitrary personal value.

```powershell
Get-FileHash .\DS_Server_ver.b2.0.0.apk -Algorithm SHA256
```

An owner can supply `tools/audit_public.py --denylist-file <external-file>` with
a private JSON list outside the repository. Reports show paths/types/line numbers,
not matched values. Inspect nested archives/bytecode as well. No automated scan
is a mathematical guarantee against every unknown secret.

The current replacement remains b2.0.0. Publish only the final bilingual assets
and their new checksums; do not mix the earlier and replacement ZIP/APK files.

References: [GitHub secret scanning](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning),
[Android application identity](https://developer.android.com/build/configure-app-module),
[MIT](https://opensource.org/license/mit).

