// Constant trip counts, exact: each statement is one operation and a function
// call one more.
// RUN: %cost --entry 'loops' --entry 'stepped' %s %flags | FileCheck %s
// CHECK-LABEL: "loops":
// CHECK: "polynomial": "167"
// CHECK: "ledger": []
// CHECK-LABEL: "stepped":
// CHECK: "polynomial": "42"

int loops() {
  int S = 0;
  for (int I = 0; I < 10; ++I)
    S += I;
  for (int I = 10; I > 0; --I)
    for (int J = 0; J <= 2; ++J)
      S += J;
  return S;
}

int stepped() {
  int S = 0;
  for (unsigned I = 3; I < 20; I += 2)
    S += I;
  for (unsigned I = 4; I-- > 0;)
    S -= I;
  return S;
}
