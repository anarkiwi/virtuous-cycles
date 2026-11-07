#ifdef BOGUS
#error built with BOGUS
#endif
#include "shared.h"

namespace {
constexpr int kConf = 1;
}

int entry(const Base &B) {
  int S = 0;
  for (int I = 0; I < kConf; ++I)
    S += across(I) + twice(I) + B.work();
  return S;
}
