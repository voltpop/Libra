# services

Optional supporting servers for the federation. **Anyone can run one, a user can use several,
and the device works without any of them.** They are untrusted: they hold only public data
and ciphertext, and only the apps (never the device) talk to them.

Planned (nothing built yet):
- **Key server:** publishes public keys and, with the owner's consent, certifications for the
  web of trust. keys.openpgp.org strips third-party certifications, so a server that keeps
  them may be needed (for example Hockeypuck, *verify*).
- **Backup server:** stores encrypted backups for fetching on a new device. It holds
  ciphertext only; the key is the recovery key, which never reaches the server.

Prefer existing protocols (OpenPGP keyservers, WKD, a plain store) over inventing new ones.
Each server gets its own threat model before it is built.
