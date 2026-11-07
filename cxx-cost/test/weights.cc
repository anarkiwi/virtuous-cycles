// Each kind of operation can be given its own cost.
// RUN: %cost --entry 'f' %s %flags | FileCheck --check-prefix=PLAIN %s
// RUN: %cost --entry 'f' --weights %S/Inputs/weights.json %s %flags | FileCheck --check-prefix=WEIGHTED %s
// Entry, `S = 0`, the test, `S = 1`, the return: five operations.
// PLAIN: "polynomial": "5"
// A call 100, two statements and a return 2 each, a test 10: 100 + 2 + 10 + 2 + 2.
// WEIGHTED: "polynomial": "116"

int f(int N) {
  int S = 0;
  if (N > 0)
    S = 1;
  return S;
}
