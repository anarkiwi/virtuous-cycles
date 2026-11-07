// A switch costs its most expensive path, not the sum of its cases: from each
// case label, up to the first statement that cannot fall through.
// RUN: %cost --entry 'breaks' --entry 'falls' --entry 'returns' --entry 'nested' %s %flags | FileCheck %s
// CHECK-LABEL: "breaks":
// Entry, `S = 0`, the test, then the larger case (ten statements and a break:
// 11), then the return.
// CHECK: "polynomial": "15"
// CHECK-LABEL: "falls":
// `case 0` falls into `case 1`: the path from 0 costs both (5), from 1 only its
// own (3), so 5 rather than the sum of 8.
// CHECK: "polynomial": "9"
// CHECK-LABEL: "returns":
// CHECK: "polynomial": "5"
// CHECK-LABEL: "nested":
// A loop's own break is not the switch's: the case still falls through, so the
// path is the loop (52) and `case 1` (2).
// CHECK: "polynomial": "58"
// CHECK: "ledger": []

int breaks(int N) {
  int S = 0;
  switch (N) {
  case 0:
    S = 1;
    S = 2;
    S = 3;
    S = 4;
    S = 5;
    S = 6;
    S = 7;
    S = 8;
    S = 9;
    S = 10;
    break;
  case 1:
    S = 1;
    break;
  }
  return S;
}

int falls(int N) {
  int S = 0;
  switch (N) {
  case 0:
    S += 1;
    S += 2;
  case 1:
    S += 3;
    S += 4;
    break;
  }
  return S;
}

int returns(int N) {
  switch (N) {
  case 0: {
    N = 1;
    N = 2;
    return N;
  }
  default:
    return 0;
  }
}

int nested(int N) {
  int S = 0;
  switch (N) {
  case 0:
    for (int I = 0; I < 10; ++I) {
      if (I == 5)
        break;
      S += I;
    }
  case 1:
    S += 1;
    break;
  }
  return S;
}
