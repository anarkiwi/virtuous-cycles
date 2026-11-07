#include <vc/cost.h>

constexpr unsigned kMax = 32;
using Items = vc::Capped<int, kMax>;

int scale(Items &V, int N) {
  int S = 0;
  for (int &X : V) {
#ifdef QUADRATIC
    for (int Y : V)
      X += Y;
#endif
    S += X;
  }
#ifdef UNBOUNDED
  while (N-- > 0)
    S += N;
#endif
  return S;
}
