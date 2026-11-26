#!/usr/bin/env python3
"""Sleep for a (jittered) amount of time to stand in for an expensive build."""
import os
import random
import time


def main() -> None:
    base = float(os.environ.get("SIMULATED_BUILD_SECONDS", "120"))
    jitter = float(os.environ.get("SIMULATED_JITTER_SECONDS", "30"))
    duration = max(0.0, base + random.uniform(-jitter, jitter))
    print(f"Simulating a heavy build for {duration:.0f}s "
          f"(base={base:.0f}s, jitter=+/-{jitter:.0f}s)")
    time.sleep(duration)
    print("done")


if __name__ == "__main__":
    main()
