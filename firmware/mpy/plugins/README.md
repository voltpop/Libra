# plugins

The one extension seam in `lb_oath`: a **hash backend** for HMAC, passed to the constructor:

    Oath(store, clock, backends={"SHA512": (ctor, 128)})

Use it when `hashlib` on a port lacks a hash (SHA-512 on some ESP32 builds) or to use the
ESP32-S3 hardware SHA engine.

Rules (this is a security device):
- A backend sees the OATH secret, so it is inside the trust boundary. Only the firmware's own
  boot code imports and passes plugins, from an explicit allowlist. Nothing here is discovered,
  scanned or loaded from the SD card, USB or the network.
- A backend can only implement SHA1, SHA256 or SHA512 with the right block size (64, 64, 128).
  It cannot add algorithms, read storage or reach other modules.
- Backends must be built into the signed firmware image. User-supplied code belongs on the
  untrusted host side (`apps/`), talking to the device through approved requests.
- Every backend needs a test that matches the RFC vectors (see `tests/test_lb_oath.py`).
