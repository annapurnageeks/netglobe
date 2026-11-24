# Security

netglobe is read-only and offline. It runs `lsof` to list connections, does reverse-DNS lookups on the addresses
your apps are already talking to, and looks up countries in a table bundled with the tool. It makes no network
requests of its own, uploads nothing, and cannot change, block or create any connection. The local server binds
to `127.0.0.1`.

**Found a vulnerability in netglobe itself** (e.g. the local server, or HTML injection in the globe page)? Please
report it privately via [GitHub's private vulnerability reporting](https://github.com/annapurnageeks/netglobe/security/advisories/new).
