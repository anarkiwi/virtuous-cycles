// Bounds of loop limits: arithmetic, min/max, conditionals, constant locals,
// reversed comparisons, downward and stepped counters; a counter written in
// the body is no bound.
// RUN: %cost --entry 'arith' --entry 'minmax' --entry 'shapes' --entry \
// RUN:   'written' %s %flags | FileCheck %s
// CHECK-LABEL: "arith":
// CHECK: "polynomial": "3*kA*kB + 15*kA + 9*kB + 45"
// CHECK-LABEL: "minmax":
// CHECK: "polynomial": "4*? + 8*kA + 8*kB + 15"
// CHECK: "line": 46,
// CHECK-LABEL: "shapes":
// CHECK: "polynomial": "6*kA + 3*kB + 22"
// CHECK-LABEL: "written":
// CHECK: "polynomial": "3*? + 5"
// CHECK: "reason": "for loop with no bound on `I < 10`"
#include <algorithm>
#include <cstddef>

constexpr std::size_t kA = 10, kB = 20;

int arith(std::size_t N) {
  int S = 0;
  for (std::size_t I = 0; I < kA * kB + 2; ++I)
    S++;
  for (std::size_t I = 0; I < kA - 1; ++I)
    S++;
  for (std::size_t I = 0; I < 24 / 5; ++I)
    S++;
  for (std::size_t I = 0; I < (kB >> 1) + (N % kA) + (N & kB); ++I)
    S++;
  for (std::size_t I = 0; I < (kA << 1); ++I)
    S++;
  for (std::size_t I = 0; I < (17 >> 2) + (kA / 3) + (kB - 4); ++I)
    S++;
  return S;
}

int minmax(std::size_t N) {
  int S = 0;
  for (std::size_t I = 0; I < std::min(N, kA); ++I)
    S++;
  for (std::size_t I = 0; I < std::max(kA, kB); ++I)
    S++;
  for (std::size_t I = 0; I < std::min({kB, N, kA * kB}); ++I)
    S++;
  for (std::size_t I = 0; I < std::max(N, kA); ++I)
    S++;
  return S;
}

int shapes(bool Wide) {
  int S = 0;
  const std::size_t Limit = Wide ? kA : kB;
  for (std::size_t I = 0; Limit > I; ++I)
    S++;
  for (std::size_t I = kA; I >= 1; I -= 1)
    S++;
  for (std::size_t I = 0; I != 9; I += 3)
    S++;
  return S;
}

int written(int N) {
  int S = 0;
  for (int I = 0; I < 10; ++I)
    I = N;
  return S;
}
