#include "shared.h"

namespace {
constexpr int kConf = 2;
}

struct Impl : Base {
  int work() const override {
    int S = 0;
    for (int I = 0; I < kConf; ++I)
      S += I;
    return S;
  }
};

int across(int X) { return X + kConf; }
