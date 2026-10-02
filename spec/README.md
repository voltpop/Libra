# spec

Everything that crosses a boundary is specified here before it is coded: device to host (USB),
device to phone (BLE), device to device (the key-signing dance), and the backup file.

Planned documents (none written yet):
- Key-exchange protocol: byte layout, QR payloads, BLE messages, certification levels
- Backup file format, versioned and authenticated
- Host and device protocol: how the host tool reaches the device (open decision)
- Companion protocol over BLE: pairing, login relay, bulk transfer
- Test vectors for all of the above

**Rule:** firmware and every app implement the same spec and pass the same vectors.
