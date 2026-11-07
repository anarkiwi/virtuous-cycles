// What has no bound goes in the ledger with its place, and costs `?`.
// RUN: %cost --entry 'drain' --entry 'walk' --entry 'retry' %s %flags | \
// RUN:   FileCheck %s
// CHECK-LABEL: "drain":
// CHECK: "polynomial": "2*? + 3"
// CHECK: "?": 1
// CHECK: "kind": "loop",
// CHECK-NEXT: "function": "drain",
// CHECK-NEXT: "file": "{{.*}}unbounded.cc",
// CHECK-NEXT: "line": 27,
// CHECK-NEXT: "column": 3,
// CHECK-NEXT: "reason": "while loop with no bound"
// CHECK-LABEL: "walk":
// CHECK: "polynomial": "3*? + 4"
// CHECK: "line": 34,
// CHECK: "reason": "range over const std::vector<int>, which has no capacity"
// CHECK-LABEL: "retry":
// CHECK: "polynomial": "3*?^2 + 3*? + 2"
// CHECK: "?": 2
// CHECK: "line": 40,
// CHECK: "reason": "do loop with no bound"
// CHECK: "line": 41,
// CHECK: "reason": "for loop with no bound"
#include <vector>

int drain(int N) {
  while (N > 0)
    N /= 2;
  return N;
}

int walk(const std::vector<int> &V) {
  int S = 0;
  for (int X : V)
    S += X;
  return S;
}

int retry(int N) {
  do {
    for (int I = 0; I < N; I += N)
      --N;
  } while (N > 3);
  return N;
}
