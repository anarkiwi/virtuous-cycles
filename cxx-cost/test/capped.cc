// Loops over declared capacities: Capped, std::array and C arrays, by range
// and by index; nested capped loops are degree 2 in the capacity.
// RUN: %cost --entry 'pairs' --entry 'scan' --entry 'grid' %s %flags | \
// RUN:   FileCheck %s
// CHECK: "symbols": {
// CHECK-NEXT: "kBins": 16,
// CHECK-NEXT: "kMaxBoxes": 64,
// CHECK-NEXT: "kRows": 8
// CHECK-LABEL: "pairs":
// CHECK: "polynomial": "2*kMaxBoxes^2 + 2*kMaxBoxes + 4"
// CHECK: "degree": {
// CHECK-NEXT: "kMaxBoxes": 2
// CHECK-LABEL: "scan":
// CHECK: "polynomial": "2*kBins + 16*kMaxBoxes + 12"
// CHECK-LABEL: "grid":
// CHECK: "polynomial": "3*kBins*kMaxBoxes + 3*kBins + 2*kRows + 5"
// CHECK: "ledger": []
#include <array>
#include <vc/cost.h>

constexpr unsigned kMaxBoxes = 64;
constexpr unsigned kBins = 16;
using Boxes = vc::Capped<int, kMaxBoxes>;

int pairs(const Boxes &A, const Boxes &B) {
  int S = 0;
  for (int X : A)
    for (int Y : B)
      S += X * Y;
  return S;
}

int scan(const Boxes &A, const std::array<int, kBins> &H) {
  int S = 0;
  for (unsigned I = 0; I < A.size(); ++I)
    S += A[I];
  for (unsigned I = 0; I < A.capacity(); ++I)
    S += A[I];
  for (int V : H)
    S += V;
  return S;
}

struct Grid {
  VC_SYMBOL(kRows) static constexpr unsigned Rows = 8;
  int Cells[kBins][kMaxBoxes];
  int Totals[Rows];
};

int grid(Grid &G) {
  int S = 0;
  for (auto &Row : G.Cells)
    for (unsigned J = 0; J < kMaxBoxes; ++J)
      S += Row[J];
  for (int T : G.Totals)
    S += T;
  return S;
}
