# lb_samples.py - canned QR payloads and host requests for QA (shared by the browser simulator
# and the Pico console). Test data only.

SAMPLES = [
    ("Good TOTP (Lab, 8 digits)",
     b"otpauth://totp/Lab:rfc?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&digits=8&issuer=Lab"),
    ("Good HOTP (Router)",
     b"otpauth://hotp/Router:admin?secret=OZYG4LLEMVWW6LLTMVRXEZLUFUYDAMBR&counter=5&issuer=Router"),
    ("Already added (GitHub)",
     b"otpauth://totp/GitHub:alice?secret=JBSWY3DPEHPK3PXP&issuer=GitHub"),
    ("Bad: unknown parameter", b"otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&image=http://evil"),
    ("Bad: look-alike name (RLO)", b"otpauth://totp/bob%E2%80%AEevil?secret=JBSWY3DPEHPK3PXP"),
    ("Unknown QR: a web link", b"https://example.com/pay?to=attacker"),
    ("Unknown QR: binary junk", b"\x00\x01\x1b[31mred\xff\xfe"),
]

HOST_REQUESTS = {
    "AUTH": "Login to git.example.com",
    "SIGN": "Sign commit 4f2a9c",
    "DECRYPT": "Decrypt backup.tar.gpg",
}
REPLACEMENT = {
    "AUTH": "Login to evil.example.com",
    "SIGN": "Sign release v2.0.1",
    "DECRYPT": "Decrypt payroll.xlsx.gpg",
}
