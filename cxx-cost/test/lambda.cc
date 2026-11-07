// Lambdas are functions; a callable passed to a modelled algorithm is
// charged once per element, and a sort is n log2 n.
// RUN: %cost --entry 'apply' --entry 'each' --entry 'order' %s %flags | \
// RUN:   FileCheck %s
// CHECK-LABEL: "apply":
// CHECK: "polynomial": "4*kN + 11"
// CHECK-LABEL: "each":
// CHECK: "polynomial": "2*kN + 10"
// CHECK-LABEL: "order":
// CHECK: "polynomial": "kN*log2(kN) + 12"
// CHECK: "ledger": []
#include <algorithm>
#include <vc/cost.h>

constexpr unsigned kN = 32;
using Values = vc::Capped<int, kN>;

int apply(const Values &V) {
  auto Sum = [&] {
    int S = 0;
    for (int X : V)
      S += X;
    return S;
  };
  return Sum() + Sum() * 0;
}

int each(Values &V) {
  std::for_each(V.begin(), V.end(), [](int &X) { X *= 2; });
  return 0;
}

int order(Values &V) {
  std::sort(V.begin(), V.end());
  return V.size();
}
