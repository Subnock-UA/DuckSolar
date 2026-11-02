# Security and privacy

[English](SECURITY.md) · [Українська](SECURITY_UK.md)

The public source contains no ready-made accounts, private keys or the author's
working profiles/logs. Your own settings belong in app-private storage or the
separate Windows runtime directory, not the repository.

Never post passwords, tokens, pairing codes, keystores, full config.json files
or unredacted log archives in public issues. Remove your PN/serials, MAC/IP/domain,
precise coordinates, computer name, system paths and usernames. Logs can contain
these without a field named password. Language preferences are local; runtime
translation does not send application text or user data to a translation service.

Provide versions, OS, reproduction steps and a redacted example. Use private
vulnerability reporting when the repository offers it; otherwise agree a private
channel with the owner without initially disclosing secrets. Do not invent an
author email or support endpoint.

The API uses TLS1.3 and identity verification. Helper is an HTTP tool for a trusted
LAN and must not be internet-facing. The owner configures remote networking.

If a secret is published, revoke/rotate it. Deleting the file alone does not
remove Git history or other copies. Public certificate fingerprints/checksums
are not private signing keys.
