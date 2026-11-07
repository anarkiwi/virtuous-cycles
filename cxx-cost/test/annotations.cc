// Annotations: a loop bound, a statement or function cost, the size of a
// parameter, field or return value, and an annotation that does not parse.
// RUN: %cost --entry 'annotated' --entry 'sized' --entry 'broken' --entry \
// RUN:   'shaped' %s %flags | FileCheck %s
// CHECK: "F.Bins": null,
// CHECK-NEXT: "kHits": 8,
// CHECK-NEXT: "kSamples": 4096,
// CHECK-NEXT: "nfft": null
// CHECK-LABEL: "annotated":
// CHECK: "polynomial": "2*kHits*kSamples + 7*kSamples + 6"
// CHECK: "ledger": []
// CHECK-LABEL: "sized":
// CHECK: "polynomial": "5*kHits + 6*nfft + 10"
// CHECK-LABEL: "broken":
// CHECK: "kind": "annotation",
// CHECK: "reason": "cannot parse \"kSamples +\""
// CHECK: "kind": "annotation",
// CHECK: "reason": "a bound on something that is not a loop"
#include <vc/cost.h>
#include <vector>

constexpr int kSamples = 4096;
VC_SYMBOL(kHits) constexpr int Hits = 8;

VC_COST(5 * kSamples) void fft(float *X);

int annotated(float *X, int N) {
  int S = 0;
  VC_BOUND(kHits * kSamples)
  while (N > 0)
    --N;
  VC_COST(2 * kSamples + 1) S += N;
  fft(X);
  return S;
}

struct Frame {
  VC_SIZE(nfft) std::vector<float> Bins;
  VC_SIZE(kHits) int Count() const { return 3; }
};

int sized(const Frame &F, VC_SIZE(nfft) int N) {
  int S = 0;
  for (int I = 0; I < N; ++I)
    S += I;
  for (float B : F.Bins)
    S += B;
  for (int I = 0; I < F.Count(); ++I)
    S += I;
  return S;
}

int broken(int N) {
  VC_BOUND(kSamples +) while (N > 0)-- N;
  VC_BOUND(kSamples) N += 1;
  return N;
}

int shaped(int N, int M) {
  VC_BOUND((kHits + 1) ^ 2 * log2(kSamples))
  while (N)
    --N;
  VC_BOUND(dsp::kHits * 2u + F.Bins + ?)
  while (M)
    --M;
  return N;
}
// CHECK-LABEL: "shaped":
// CHECK: "polynomial": "2*kHits^2*log2(kSamples) + 4*kHits*log2(kSamples)
// CHECK-SAME: + 2*? + 2*F.Bins + 4*kHits + 2*log2(kSamples) + 4"
// CHECK: "reason": "annotated as unbounded: dsp::kHits * 2u + F.Bins + ?"
