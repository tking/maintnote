# maintnote Documentation

`maintnote` is a Python 3.10+ library and command-line tool (CLI) for network maintenance notifications.
It implements IETF [**`draft-gunter-calext-maintenance-notifications-00`**](https://datatracker.ietf.org/doc/html/draft-gunter-calext-maintenance-notifications-00) (*Maintenance Notification Improvements Using iCalendar*).

## Why Use `maintnote`?

Network providers usually send maintenance notifications as plain-text emails.
Plain-text emails force teams to write fragile parsers or copy dates into calendars and tickets manually.

`draft-gunter-calext-maintenance-notifications-00` adds structured `X-MAINTNOTE-*` fields to standard RFC 5545 iCalendar (`VCALENDAR` and `VEVENT`) payloads.
With `maintnote`, providers generate compliant maintenance notifications.
Consumers then parse, validate, and automate maintenance windows with standard calendar compatibility.

## Audience

This documentation serves software developers, network engineers, and DevOps engineers who build or operate maintenance automation:

- **Software developers** who integrate iCalendar maintenance parsing, generation, and validation into Python services.
- **Network engineers** who generate maintenance notifications for customers or connect received notifications to change and traffic workflows.
- **DevOps engineers** who run automated pipelines, CLI checks, state stores, and ticket integrations from email or CalDAV feeds.

## How `maintnote` Works

A **provider** (carrier, internet exchange, or cloud operator) creates a maintenance notification with a unique `UID` and `SEQUENCE=0`.
When the window changes, the provider sends a new notification with the same `UID` and a higher `SEQUENCE`.
A **consumer** (customer NOC, ticket system, or automation pipeline) parses each notification, tracks `(provider, uid)` state, and ignores duplicate or stale messages.

## Documentation Map

- **[Getting Started](getting-started.md):** Install `maintnote`, parse `.ics` files, create notifications, and run the CLI.
- **[Provider and Consumer Workflows](workflows.md):** Run all five lifecycle stages, track state, and automate tickets.
- **[Security and Transport](security-and-transport.md):** Prevent automatic calendar entries, sign and verify OpenPGP emails, get `ALTREP` JSON metadata, and use CalDAV over TLS.
- **[Specification Compliance](specification-compliance.md):** Map each section of the Internet-Draft to its implementation in `maintnote`.
- **[API Reference](api-reference.md):** Look up public modules, classes, functions, and exceptions.
