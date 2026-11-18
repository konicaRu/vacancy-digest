These are synthetic TEST ONLY certificates and a TEST ONLY server private key,
generated for loopback TLS handshakes. They protect no real service or data.

`ca.pem` signs `server.pem` and `wrong-host.pem`; `untrusted.pem` is self-signed.
All server certificates use `server.key`. The CA private key is not included.
Certificates expire in 2036; regenerate before then if tests are still used.
