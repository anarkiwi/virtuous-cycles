// VC_TOTAL bounds an inner loop's trip count summed over every iteration of the
// loops around it, where VC_BOUND would multiply it by them.
// RUN: %cost --entry 'shared' --entry 'each' --entry 'nested' %s %flags | FileCheck %s
// Nine channels draw on one pool of kPool notes: the inner loop's body runs
// kPool times in all, not kChannels * kPool.
// CHECK-LABEL: "shared":
// CHECK: "polynomial": "4*kChannels + 3*kPool + 5"
// CHECK: "ledger": []
// The same loop with a per-iteration bound is kChannels times as costly.
// CHECK-LABEL: "each":
// CHECK: "polynomial": "3*kChannels*kPool + 4*kChannels + 5"
// A total inside a total reaches past both loops: the inner 2*kPool body (6) is
// not scaled by the middle loop, only its setup is.
// CHECK-LABEL: "nested":
// CHECK: "polynomial": "4*kChannels + 10*kPool + 5"
// CHECK-NOT: "?"
#include <vc/cost.h>

constexpr int kChannels = 9;
constexpr int kPool = 16;

int shared(const int *Counts) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    VC_TOTAL(kPool) for (int J = 0; J < Counts[I]; ++J) S += J;
  return S;
}

int each(const int *Counts) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    VC_BOUND(kPool) for (int J = 0; J < Counts[I]; ++J) S += J;
  return S;
}

int nested(const int *Counts) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    VC_TOTAL(kPool) for (int J = 0; J < Counts[I]; ++J)
        VC_TOTAL(kPool * 2) for (int K = 0; K < J; ++K) S += K;
  return S;
}
