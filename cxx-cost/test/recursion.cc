// Recursion is unbounded unless a function in the cycle declares how many
// activations it makes; mutual recursion is one cycle.
// RUN: %cost --entry 'fact' --entry 'even' --entry 'depth' %s %flags | \
// RUN:   FileCheck %s
// CHECK-LABEL: "fact":
// CHECK: "polynomial": "4*?"
// CHECK: "kind": "recursion",
// CHECK-NEXT: "function": "fact",
// CHECK-LABEL: "even":
// CHECK: "polynomial": "4*?"
// CHECK: "function": "even",
// CHECK: "function": "odd",
// CHECK-LABEL: "depth":
// CHECK: "polynomial": "2*kDepth"
// CHECK: "ledger": []
#include <vc/cost.h>

int fact(int N) {
  if (N < 2)
    return 1;
  return N * fact(N - 1);
}

bool odd(unsigned N);
bool even(unsigned N) { return N == 0 ? true : odd(N - 1); }
bool odd(unsigned N) { return N == 0 ? false : even(N - 1); }

constexpr int kDepth = 32;

VC_RECURSION(kDepth) int depth(int N) { return N > 0 ? depth(N - 1) + 1 : 0; }
