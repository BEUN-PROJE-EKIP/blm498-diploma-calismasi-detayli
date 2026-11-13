// Saat eşliği kanıtı için: iki Python okuması arasında MonotonikNs() ve std::chrono::steady_clock değerini yazar.
#include <chrono>
#include <cstdio>
#include "saat.hh"

int main()
{
  const int64_t a = MonotonikNs();
  const int64_t s = std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
  const int64_t b = MonotonikNs();
  std::printf("%lld %lld %lld\n", static_cast<long long>(a), static_cast<long long>(s), static_cast<long long>(b));
  return 0;
}
