// Command tokenbucket reports how many of N events a limiter would allow.
package main

import (
	"flag"
	"fmt"
	"time"

	"example.com/tokenbucket"
)

func main() {
	rate := flag.Float64("rate", 5, "tokens refilled per second")
	burst := flag.Float64("burst", 5, "maximum burst")
	events := flag.Int("events", 10, "events to offer")
	flag.Parse()

	l := tokenbucket.New(*rate, *burst)
	now := time.Now()
	allowed := 0
	for i := 0; i < *events; i++ {
		if l.AllowAt(now) {
			allowed++
		}
	}
	fmt.Printf("allowed %d of %d\n", allowed, *events)
}
