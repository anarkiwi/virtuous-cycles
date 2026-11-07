// A virtual call costs the join of every overrider in the analysed units; one
// with no overrider, or a declaration with no body, is in the ledger; a final
// class's call is direct.
// RUN: %cost --entry 'area' --entry 'unknown' --entry 'direct' %s %flags | \
// RUN:   FileCheck %s
// CHECK-LABEL: "area":
// CHECK: "polynomial": "3*kSides + 7"
// CHECK: "ledger": []
// CHECK-LABEL: "unknown":
// CHECK: "polynomial": "? + 2"
// CHECK: "kind": "virtual",
// CHECK: "reason": "virtual call to Abstract::run has no overrider"
// CHECK-LABEL: "direct":
// CHECK: "polynomial": "4"
#include <vc/cost.h>

constexpr int kSides = 12;

struct Shape {
  virtual ~Shape() = default;
  virtual int area() const = 0;
};

struct Square : Shape {
  int area() const override { return 4; }
};

struct Polygon : Shape {
  int area() const override {
    int S = 0;
    for (int I = 0; I < kSides; ++I)
      S += I;
    return S;
  }
};

struct Tri final : Shape {
  int area() const override { return 3; }
};

int area(const Shape &S) { return S.area() + 1; }

struct Abstract {
  virtual int run() = 0;
};

int unknown(Abstract &A) { return A.run(); }

int direct(const Tri &T) { return T.area() + 1; }
