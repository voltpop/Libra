# apps/shared

The single implementation of `spec/` used by the command-line tool, the desktop app and the
mobile apps: message encoding, the backup format, pairing and login relay.

**Open decision:** the implementation language. It must build for desktop, iOS and Android
and be easy to test against the vectors in `spec/`. Nothing is created until that is decided.
