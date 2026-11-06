#include <cstddef>

extern int opaque(int x);

int linear(const int *a, std::size_t n) {
  int s = 0;
  for (std::size_t i = 0; i < n; ++i) {
    s += a[i];
  }
  return s;
}

int quadratic(const int *a, std::size_t n) {
  int s = 0;
  for (std::size_t i = 0; i < n; ++i) {
    for (std::size_t j = 0; j < n; ++j) {
      s += a[i] * a[j];
    }
  }
  return s;
}

int constant(int x) { return x * 2 + 1; }

int unknown(int x) {
  int s = 0;
  for (int i = 0; i < opaque(x); ++i) {
    s += i;
  }
  return s;
}

namespace dsp {

int halving(unsigned n) {
  int s = 0;
  for (unsigned i = n; i > 0; i /= 2) {
    ++s;
  }
  return s;
}

int product(std::size_t m, std::size_t n) {
  int s = 0;
  for (std::size_t i = 0; i < m; ++i) {
    for (std::size_t j = 0; j < n; ++j) {
      ++s;
    }
  }
  return s;
}

struct Window {
  std::size_t len;
  int sum(const int *a) const {
    int s = 0;
    for (std::size_t i = 0; i < len; ++i) {
      s += a[i];
    }
    return s;
  }
  int sum(const int *a, std::size_t n) const {
    return linear(a, n) + static_cast<int>(len);
  }
};

} // namespace dsp

int use(const int *a, std::size_t n) {
  dsp::Window w{n};
  return w.sum(a) + w.sum(a, n);
}
