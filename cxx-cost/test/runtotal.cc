// VC_RUN_TOTAL bounds a loop's trip count summed over every execution of it in
// one run of the entry point, across calls: where VC_BOUND multiplies by the
// loops around the calls, and VC_TOTAL by them too (its total is per function).
// RUN: %cost --entry 'perChannel' --entry 'perBound' --entry 'perTotal' --entry 'twice' --entry 'joined' --entry 'deep' --entry 'ring' --entry 'either' --entry 'Pool::work' %s %flags | FileCheck %s
// Nine channels call work(), which loops over a pool all of them draw on: the
// loop runs kPool times in all. work() alone costs 5 + 3*kPool; each call from
// the loop adds its 5 (and 3 for the loop's own bookkeeping) 9 times.
// CHECK-LABEL: "perChannel":
// CHECK: "polynomial": "8*kChannels + 3*kPool + 5"
// CHECK: "ledger": []
// The same callee with a per-call bound is charged kPool for every channel.
// CHECK-LABEL: "perBound":
// CHECK: "polynomial": "3*kChannels*kPool + 8*kChannels + 5"
// VC_TOTAL is per function activation, so each call still pays it in full.
// CHECK-LABEL: "perTotal":
// CHECK: "polynomial": "3*kChannels*kPool + 8*kChannels + 5"
// Two call sites each count it: one run's total, once per site.
// CHECK-LABEL: "twice":
// CHECK: "polynomial": "6*kPool + 12"
// A call joined with another (here by `?:`) is scaled by the loops around it:
// the conservative case, charged like a per-call bound.
// CHECK-LABEL: "joined":
// CHECK: "polynomial": "3*kChannels*kPool + 8*kChannels + 5"
// The total passes up through more than one call (10 per channel here: the
// extra call level adds two statements).
// CHECK-LABEL: "deep":
// CHECK: "polynomial": "10*kChannels + 3*kPool + 5"
// In a recursive cycle the run-wide total is scaled like any other cost: ring
// runs up to 3 times, and each run reaches work() from two sites in it.
// CHECK-LABEL: "ring":
// CHECK: "polynomial": "18*kPool + 42"
// CHECK: "ledger": []
// A call that could reach either of two functions costs the larger, scaled.
// CHECK-LABEL: "either":
// CHECK: "polynomial": "3*kChannels*kPool + 8*kChannels + 5"
// CHECK-LABEL: "Pool::work":
// CHECK: "polynomial": "3*kPool + 5"
#include <vc/cost.h>

constexpr int kChannels = 9;
constexpr int kPool = 16;

struct Pool {
  int Count;
  int work() {
    int S = 0;
    VC_RUN_TOTAL(kPool) for (int J = 0; J < Count; ++J) S += J;
    return S;
  }
  int bounded() {
    int S = 0;
    VC_BOUND(kPool) for (int J = 0; J < Count; ++J) S += J;
    return S;
  }
  int total() {
    int S = 0;
    VC_TOTAL(kPool) for (int J = 0; J < Count; ++J) S += J;
    return S;
  }
};

int perChannel(Pool *P) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    S += P[I].work();
  return S;
}

int perBound(Pool *P) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    S += P[I].bounded();
  return S;
}

int perTotal(Pool *P) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    S += P[I].total();
  return S;
}

int twice(Pool *P) { return P[0].work() + P[1].work(); }

int joined(Pool *P, bool Big) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    S += Big ? P[I].work() : P[I].bounded();
  return S;
}

int middle(Pool &P) { return P.work() + 1; }

int deep(Pool *P) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    S += middle(P[I]);
  return S;
}

VC_RECURSION(3) int ring(Pool &P, int N) {
  if (N == 0)
    return P.work();
  return ring(P, N - 1) + P.work();
}

int either(Pool *P) {
  int S = 0;
  for (int I = 0; I < kChannels; ++I)
    VC_TARGETS(Pool::work, Pool::bounded) S += 0;
  return S;
}
