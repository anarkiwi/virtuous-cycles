// Every statement form: switch, try, forward and backward goto, condition
// variables, constructor initialisers, default arguments, statement
// expressions; constructors, annotated definitions and virtual methods.
// RUN: %cost --entry 'forms' --entry 'build' --entry 'annotated' --entry \
// RUN:   'pick' --entry 'Ring::Ring' %s %flags | FileCheck %s
// CHECK-LABEL: "forms":
// CHECK: "polynomial": "22*?"
// CHECK: "reason": "backward goto"
// CHECK-LABEL: "build":
// CHECK: "polynomial": "3*kSlots + 9"
// CHECK-LABEL: "annotated":
// CHECK: "polynomial": "kSlots + 1"
// CHECK-LABEL: "pick":
// CHECK: "polynomial": "kSlots^2 + 2"
// CHECK-LABEL: "Ring::Ring":
// CHECK: "polynomial": "3*kSlots + 6"
#include <vc/cost.h>

constexpr int kSlots = 8;

int helper(int X = kSlots) { return X; }

int forms(int N) {
  int S = 0;
  switch (N) {
  case 0:
    S = 1;
    break;
  default:
    S = 2;
  }
  try {
    S += helper();
  } catch (...) {
    S = 0;
  }
  if (int K = helper(N))
    S += K;
  if (N > 3)
    goto done;
again:
  if (--N > 0)
    goto again;
done:
  S += ({
    int T = N;
    T;
  });
  return S;
}

struct Ring {
  Ring(int N) : Size(helper(N)) {
    for (int I = 0; I < kSlots; ++I)
      Slots[I] = I;
  }
  int Size;
  int Slots[kSlots];
};

int build(int N) {
  Ring R(N);
  return R.Size;
}

VC_COST(kSlots + 1) int annotated(int N) {
  while (N)
    --N;
  return N;
}

struct Policy {
  VC_COST(kSlots *kSlots) virtual int choose() const;
};

int pick(const Policy &P) { return P.choose(); }
