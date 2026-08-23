# Security Policy

## Supported versions

| version | supported |
|---------|-----------|
| 0.10.x  | ✅ |
| < 0.10  | ❌ upgrade first |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting on this repository
(**Security → Report a vulnerability**) — it reaches the maintainers directly
and keeps details private until a fix ships.

Include what you can:

- affected version / commit (or image tag)
- endpoint and request that triggers the issue
- impact you observed or suspect

You will get an initial response within **7 days**. If the report is accepted
we will keep you updated as we work on a fix, and credit you in the release
notes (unless you prefer to stay anonymous).

## Scope notes

anbar's security model assumes:

- the service binds to loopback only; TLS termination and exposure happen at
  your reverse proxy. Anything that requires *direct* access to the container
  port from another machine is out of scope.
- admin/uploader keys are bearer credentials — treat them like passwords.
- signed share links are capability URLs: anyone holding one can download the
  object until it expires or the HMAC secret rotates (`anbarctl rotate-secret`).

Out of scope: self-XSS in single-user pages, missing rate limits behind your
own trusted proxy, and anything requiring a malicious storage backend.
