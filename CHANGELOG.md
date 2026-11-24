# Changelog

## 0.1.0 (2026-11-24)

First release, for macOS.

- A live, rotating globe of every outbound connection your apps have open, with an arc from you to each one
- Names the company behind each address (reverse DNS + a bundled table of known networks) and flags trackers, ad networks, attribution and session-replay services
- Places every connection by country using a bundled, fully offline IPv4 + IPv6 to country table built from the public RIR delegation files
- A per-app panel, a terminal mode (`--once`, `--json`), and a sample demo that runs on GitHub Pages
- Read-only, no admin, no network requests of its own; works as a Claude Code skill
