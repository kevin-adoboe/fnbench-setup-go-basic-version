# tokenbucket

A token-bucket rate limiter used by the edge service.

- `limiter.go` — the limiter itself
- `cmd/tokenbucket` — a small CLI that reports how many events would be allowed

Run the tests with `go test ./...`.
