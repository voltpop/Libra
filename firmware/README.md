# firmware

ESP-IDF project (C) for the ESP32-S3. One component per module, named in the software map
(`software-map.html`):

`boot profile session keystore crypto time oath openpgp fido xch backup qr qrparse ble usb
storage vault ui` and the drivers `display input camera fp haptic rtc power se sdcard usbhost`.

Planned layout (not created yet):
- `components/<name>/include/lb_<name>.h`: public header, everything prefixed `lb_`
- `main/`: start-up and task wiring
- `test/`: host-side unit tests and fuzzing (`qrparse`, `storage`, `openpgp`, `fido`, `xch`)
- `partitions.csv`, `sdkconfig.defaults`

Calls go down the layers, callbacks go up, and `session` alone grants approval. The build of
`software-map.html` enforces the layering on the planned API.
