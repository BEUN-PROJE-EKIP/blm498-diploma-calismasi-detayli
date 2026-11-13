// Ortak monotonik saat: CLOCK_MONOTONIC, nanosaniye. Python tarafındaki time.monotonic_ns() ile aynı saattir
// (CPython Linux'ta clock_gettime(CLOCK_MONOTONIC) kullanır); eşlik saat_kontrol aracıyla sınanır.
#pragma once
#include <cstdint>
#include <ctime>

inline int64_t MonotonikNs()
{
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return static_cast<int64_t>(ts.tv_sec) * 1000000000LL + ts.tv_nsec;
}
