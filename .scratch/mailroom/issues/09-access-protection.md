# 09: Only the owner can reach the web page

**What to build:** The web page is reachable only through Cloudflare Access. SMS Mailroom listens on the loopback address only and validates the Cloudflare Access JWT on every request against the configured team domain and audience tag, so a tunnel misconfiguration cannot expose Messages. SMS Mailroom has no accounts or passwords of its own.

**Blocked by:** 01

**Status:** done

- [x] The web server binds to `127.0.0.1` only
- [x] A request without a valid Cloudflare Access JWT is rejected and reveals no Message content
- [x] A JWT with the wrong audience, an expired JWT and a JWT with a bad signature are each rejected
- [x] A request with a valid JWT is served
- [x] The team domain and audience tag come from configuration outside the repository
- [x] Validation can be switched off only by an explicit local-development setting, which is off by default
