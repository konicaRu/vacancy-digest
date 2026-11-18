# Bank TLS trust

`russian-trusted-root-ca.pem` is the public Russian Trusted Root CA certificate.
It supplements Requests' standard CA bundle **only** for `https://www.tbank.ru/`
and `https://job.alfabank.ru/` in `vd.sources.make_session`. Chain validity and
hostname checks remain enabled. No Windows trust-store or certifi file is edited.
Explicit Requests CA overrides (including REQUESTS_CA_BUNDLE) take precedence.

Source: [T-Bank certificate instructions](https://status.tbank-online.com/certificates/),
Windows root download:
https://help-static2.tbank-online.com/certs/Windows/Root/Russian_Trusted_Root_CA.cer

Downloaded on 2026-11-18 using standard, verified HTTPS and converted DER → PEM.
The DER certificate matches the root observed in T-Bank's TLS chain.

- Subject/issuer: Russian Trusted Root CA, The Ministry of Digital Development and Communications, RU.
- DER SHA-256: `d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31`.
- Serial: `1000`; expires 2032-02-27 21:04:15 UTC.

Requests >=2.32.3 is required for per-request TLS pool-context configuration.
Replace the certificate from an official, independently verified source when it
expires or is rotated; never trust a replacement merely because a server presents it.
