// VC_TARGETS names what a call through a pointer can reach: the statement costs
// one operation and the most expensive of them.
// RUN: %cost --entry 'Pulse::dispatch' --entry 'Pulse::cheap' --entry 'Pulse::dear' --entry 'Pulse::lost' %s %flags | FileCheck %s
// CHECK-LABEL: "Pulse::dispatch":
// CHECK: "polynomial": "3*kSteps + 7"
// CHECK: "ledger": []
// CHECK-LABEL: "Pulse::cheap":
// CHECK: "polynomial": "2"
// CHECK-LABEL: "Pulse::dear":
// CHECK: "polynomial": "3*kSteps + 5"
// A name matching no analysed function is in the ledger.
// CHECK-LABEL: "Pulse::lost":
// CHECK: "kind": "annotation"
// CHECK: "reason": "VC_TARGETS names no analysed function: Pulse::nowhere"
#include <vc/cost.h>

constexpr int kSteps = 4;

struct Pulse {
  bool (Pulse::*Next)() = &Pulse::cheap;
  bool cheap() { return true; }
  bool dear() {
    int S = 0;
    for (int I = 0; I < kSteps; ++I)
      S += I;
    return S > 0;
  }
  bool dispatch() { VC_TARGETS(Pulse::cheap, Pulse::dear) return (this->*Next)(); }
  bool lost() { VC_TARGETS(Pulse::nowhere) return (this->*Next)(); }
};
