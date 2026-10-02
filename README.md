# Libra

A handheld, open-hardware security device that is **not your phone**. It is an OTP token,
an open FIDO2 and OpenPGP security key, an in-person key-signing tool for a web of trust,
and an encrypting storage broker. It is minimal on purpose: a small screen, a D-pad and one
hold-to-approve button, so the focus stays on the person at the other end.

**Status:** design phase. Nothing is built or tested. The current stage is **v0 (beta)**,
a breadboard of modules on an ESP32-S3-DevKitC-1. v1 (PCB, case, battery) gets its own document.

## The design

| File | What it is |
|---|---|
| `LIBRA.md` | The design document (the source of truth) |
| `report.html` | The design report, built from `LIBRA.md` |
| `software-map.html` | Components, functions and call flows of the firmware, built from `tools/softmap_data.py` |

Rebuild after editing:

```
python3 tools/build_report.py      # needs: pip install markdown
python3 tools/build_softmap.py     # refuses to build if the layering rules are broken
```

## Repository map

| Directory | Holds | Status |
|---|---|---|
| `spec/` | Protocols and formats, with test vectors | not started |
| `hardware/` | v0 wiring and BOM; v1 PCB and enclosure | not started |
| `firmware/` | ESP-IDF firmware, one component per module | not started |
| `apps/` | Untrusted clients: shared library, command-line tool, desktop, mobile | not started |
| `services/` | A hosted piece, only if one is chosen | undecided |
| `test/` | Interoperability and hardware-in-loop tests | not started |
| `tools/` | Scripts that build the design documents | working |

The layout and the rules behind it are in the **Repository layout** section of `LIBRA.md`.

## Licensing

Intent: CERN-OHL for the hardware and open licences for the firmware, apps and spec. The
specific licences are **not chosen yet**; each directory will carry its own once they are.
