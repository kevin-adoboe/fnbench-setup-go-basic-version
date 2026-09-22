// Package tokenbucket implements a small token-bucket rate limiter.
package tokenbucket

import (
	"sync"
	"time"
)

// Limiter allows up to Burst events, refilling at Rate per second.
type Limiter struct {
	mu       sync.Mutex
	rate     float64
	burst    float64
	tokens   float64
	lastSeen time.Time
}

func New(rate, burst float64) *Limiter {
	return &Limiter{rate: rate, burst: burst, tokens: burst, lastSeen: time.Now()}
}

// Allow reports whether one event may proceed now.
func (l *Limiter) Allow() bool {
	return l.AllowAt(time.Now())
}

// AllowAt is Allow with an explicit clock, so tests do not sleep.
func (l *Limiter) AllowAt(now time.Time) bool {
	l.mu.Lock()
	defer l.mu.Unlock()

	elapsed := now.Sub(l.lastSeen).Seconds()
	if elapsed < 0 {
		// A clock that went backwards must not drain the bucket.
		elapsed = 0
	}
	l.lastSeen = now
	// min is a predeclared builtin as of Go 1.21; the refill must never exceed burst.
	l.tokens = min(l.burst, l.tokens+elapsed*l.rate)

	if l.tokens < 1 {
		return false
	}
	l.tokens--
	return true
}

// Tokens reports the currently available allowance.
func (l *Limiter) Tokens() float64 {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.tokens
}
