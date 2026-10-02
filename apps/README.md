# apps

Clients that talk to Libra. **They are untrusted by design**: the phone and the computer are
the devices Libra exists to keep secrets away from. Every sensitive action is approved on the
device with a PTT hold.

Rules for everything under `apps/`:
- Handle only public data and ciphertext. The one exception is the recovery key, stored in the
  OS secure storage only if the user opts in.
- Never ask for or relay the unlock combo.
- Implement `spec/` through `shared/`, not by hand.

| Directory | Purpose | Status |
|---|---|---|
| `shared/` | One codec for the protocols and the backup format | not started |
| `cli/` | v0 host tool: time sync, backup and restore, firmware update | not started |
| `desktop/` | Later | reserved |
| `mobile/` | Later | reserved |
