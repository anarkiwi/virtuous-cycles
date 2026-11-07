// Loops that step a pointer or an iterator once per element, from the start of
// an array or container to its end, are bounded by its size.
// RUN: %cost --entry 'pointer' --entry 'iterator' --entry 'erasing' --entry 'partial' --entry 'macro' --entry 'spin' %s %flags | FileCheck %s
// CHECK-LABEL: "pointer":
// CHECK: "polynomial": "3*kN + 6"
// CHECK: "ledger": []
// CHECK-LABEL: "iterator":
// CHECK: "polynomial": "{{.*}}kSlots{{.*}}"
// CHECK: "ledger": []
// An iterator the body steps is not counted: it may revisit elements.
// CHECK-LABEL: "erasing":
// CHECK: "reason": "for loop with no bound on `I != V.end()`"
// A pointer that does not start at the array's base is not counted.
// CHECK-LABEL: "partial":
// CHECK: "reason": "for loop with no bound on `P < A + kN`"
// The ledger quotes the macro body, not the invocation.
// CHECK-LABEL: "macro":
// CHECK: "polynomial": "3*kN + 6"
// CHECK: "ledger": []
// CHECK-LABEL: "spin":
// CHECK: "reason": "for loop with no bound on `i < (x)`"
#include <vc/cost.h>

#include <vector>

constexpr int kN = 6;
constexpr int kSlots = 4;
#define EACH(p, a, body)                                                     \
  {                                                                          \
    for (int *p = (a); p < (a) + kN; ++p) {                                  \
      body;                                                                  \
    }                                                                        \
  }

#define UP_TO(x)                                                             \
  {                                                                          \
    for (int i = 0; i < (x); ++i) {                                          \
    }                                                                        \
  }

struct Pool {
  Pool() : Items() {}
  int total() {
    int S = 0;
    for (auto I = Items.begin(); I != Items.end(); ++I)
      S += *I;
    return S;
  }
  VC_SIZE(kSlots) std::vector<int> Items;
};

int pointer() {
  int A[kN] = {};
  int S = 0;
  for (int *P = A; P < A + kN; ++P)
    S += *P;
  return S;
}

int iterator() {
  Pool P;
  return P.total();
}

int erasing(std::vector<int> &V) {
  for (auto I = V.begin(); I != V.end(); ++I)
    if (*I == 0)
      V.erase(I--);
  return 0;
}

int partial() {
  int A[kN] = {};
  int S = 0;
  for (int *P = A + 1; P < A + kN; ++P)
    S += *P;
  return S;
}

int macro() {
  int A[kN] = {};
  int S = 0;
  EACH(P, A, S += *P)
  return S;
}

void spin(int N) UP_TO(N)
