// Each template instantiation is its own function; an entry pattern naming
// the template joins its instantiations; a capacity reaching a template by
// value is named by the one constant with that value.
// RUN: %cost --entry 'total<*' --entry 'both' %s %flags | FileCheck %s
// CHECK-LABEL: "total<*":
// CHECK: "functions": [
// CHECK-NEXT: "total<16UL>",
// CHECK-NEXT: "total<64UL>"
// CHECK: "polynomial": "2*kLarge + 2*kSmall + 4"
// CHECK-LABEL: "both":
// CHECK: "polynomial": "2*kLarge + 2*kSmall + 10"
#include <vc/cost.h>

constexpr std::size_t kSmall = 16, kLarge = 64;

template <std::size_t N> int total(const vc::Capped<int, N> &V) {
  int S = 0;
  for (int X : V)
    S += X;
  return S;
}

int both(const vc::Capped<int, kSmall> &A, const vc::Capped<int, kLarge> &B) {
  return total(A) + total(B);
}
