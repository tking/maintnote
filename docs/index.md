# maintnote Documentation

`maintnote` implements [**IETF `draft-gunter-calext-maintenance-notifications-00`**](https://datatracker.ietf.org/doc/html/draft-gunter-calext-maintenance-notifications-00)
(*Maintenance Notification Improvements Using iCalendar*) for Python 3.10+.

## Why `maintnote`?

Network maintenance notifications are traditionally delivered as unstructured emails that require brittle regex parsing or manual calendar/ticket entry. `draft-gunter-calext-maintenance-notifications-00` standardizes machine-parseable `X-MAINTNOTE-*` metadata inside standard RFC 5545 iCalendar (`VCALENDAR`/`VEVENT`) attachments so providers and consumers can automate maintenance tracking while retaining full compatibility with standard calendar clients.

## Documentation Map

- **[Getting Started](getting-started.md)** — Installation, parsing, creating notifications, and CLI usage.
- **[Specification Compliance](specification-compliance.md)** — Section-by-section matrix tracing every requirement in the draft to `maintnote`.
- **[Provider & Consumer Workflows](workflows.md)** — End-to-end guides for all five lifecycle workflows (Initial, Updated, Cancelled, Open, Closed).
- **[Security & Transport](security-and-transport.md)** — `METHOD` calendar safety, Email/MIME, OpenPGP (RFC 3156), `ALTREP` JSON fetching, CalDAV over TLS (RFC 4791), and out-of-band verification.
- **[API Reference](api-reference.md)** — Module, class, and function reference.
