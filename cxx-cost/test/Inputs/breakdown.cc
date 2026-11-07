constexpr int kN = 8;

int stepped() { return 1; }

int inner() {
  int S = 0;
  for (int I = 0; I < kN; ++I)
    S += I;
  return S;
}

int outer() { return inner() + stepped(); }
