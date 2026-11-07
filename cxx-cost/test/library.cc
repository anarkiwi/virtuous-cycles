// The standard library's models: ranges over capacities, counts, byte sizes,
// ordered containers, container growth, callables (function pointers,
// functors, generic lambdas), and ranges with no bound.
// RUN: %cost --entry 'ranges' --entry 'calls' --entry 'unsized' --entry \
// RUN:   'access' --entry 'moves' %s %flags | FileCheck %s
// CHECK-LABEL: "ranges":
// CHECK: "polynomial": "kN*log2(kN) + 3*kN + 2*kQ + 2*log2(kN) + 31"
// CHECK-LABEL: "calls":
// CHECK: "polynomial": "6*kN + 32"
// CHECK-LABEL: "unsized":
// CHECK: "polynomial": "2*? + 5"
// CHECK: "reason": "call to std::vector::insert on a range with no bound"
// CHECK: "reason": "call to std::find on a range with no bound"
// CHECK-LABEL: "access":
// CHECK: "polynomial": "4*kN + 7"
// CHECK-LABEL: "moves":
// CHECK: "polynomial": "? + 18"
// CHECK-NOT: std::move
// CHECK: "reason": "call to std::vector::operator= on a range with no bound"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <map>
#include <string>
#include <vc/cost.h>
#include <vector>

constexpr std::size_t kN = 64, kQ = 4;
using Values = vc::Capped<int, kN>;

int ranges(Values &V, std::array<int, kN> &A, int (&C)[kQ],
           VC_SIZE(kN) std::map<int, int> &M, std::vector<int> &W) {
  std::sort(A.begin(), A.end());
  std::fill_n(A.begin(), kQ, 0);
  std::memcpy(A.data(), V.begin(), kN);
  auto It = std::lower_bound(A.begin(), A.end(), 3);
  std::fill(std::begin(C), std::end(C), 1);
  M.find(*It);
  W.resize(kN);
  return std::count(A.begin() + 1, A.end(), 0) +
         std::max(std::initializer_list<int>{1, 2});
}

int twice(int X) { return 2 * X; }
struct Halve {
  int operator()(int X) const { return X / 2; }
};

int calls(Values &V) {
  std::transform(V.begin(), V.end(), V.begin(), twice);
  std::transform(V.begin(), V.end(), V.begin(), Halve());
  std::for_each(V.begin(), V.end(), [](auto &X) { X += 1; });
  return 0;
}

int unsized(std::vector<int> &W, const int *P) {
  W.insert(W.begin(), 1);
  return *std::find(P, P + 4, 3);
}

struct Owner {
  Values Items;
  Values &items() { return Items; }
};

int access(Owner &O, Values *P) {
  int S = 0;
  for (int X : O.items())
    S += X;
  for (int X : *P)
    S += X;
  return S;
}

int moves(std::vector<int> &W, std::vector<int> &X) {
  W = std::move(X);
  std::vector<int> Y(std::move(W));
  std::string S("abc");
  int *P = new int(3);
  delete P;
  X = Y;
  return std::isnan(nanf("")) + Y.size() + S.size();
}
