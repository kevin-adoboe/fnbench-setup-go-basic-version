package tokenbucket

import (
	"testing"
	"time"
)

func TestAllowConsumesBurst(t *testing.T) {
	start := time.Now()
	l := New(1, 3)
	for i := 0; i < 3; i++ {
		if !l.AllowAt(start) {
			t.Fatalf("event %d should have been allowed within the burst", i)
		}
	}
	if l.AllowAt(start) {
		t.Fatal("fourth event should be denied once the burst is spent")
	}
}

func TestRefillIsCappedAtBurst(t *testing.T) {
	start := time.Now()
	l := New(2, 4)
	l.AllowAt(start)
	// A long idle period must not refill beyond the burst.
	l.AllowAt(start.Add(time.Hour))
	if got := l.Tokens(); got > 4 {
		t.Fatalf("tokens = %v, want <= burst (4)", got)
	}
}
