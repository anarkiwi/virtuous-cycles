#include <cstddef>

extern int opaque(int x);

namespace lib {
namespace {

struct Wide {
  long a, b;
};

int scan(const int *a, std::size_t n) {
  int s = 0;
  for (std::size_t i = 0; i < n; ++i) {
    s += a[i];
  }
  return s;
}

} // namespace

template <typename T> int walk(const T *a, std::size_t n) {
  int s = 0;
  if constexpr (sizeof(T) == 1) {
    s = a[0];
  } else if constexpr (sizeof(T) == 4) {
    for (std::size_t i = 0; i < n; ++i) {
      s += a[i];
    }
  } else {
    for (int i = 0; i < opaque(static_cast<int>(n)); ++i) {
      s += static_cast<int>(a[0].a);
    }
  }
  return s;
}

template <typename F> int each(std::size_t n, F f) {
  int s = 0;
  for (std::size_t i = 0; i < n; ++i) {
    s += f(i);
  }
  return s;
}

int entry(const char *c, const int *a, std::size_t n) {
  Wide w[1] = {};
  return scan(a, n) + walk(c, n) + walk(a, n) +
         each(n, [&](std::size_t i) { return a[i]; }) +
         each(n, [&](std::size_t) { return scan(a, n); });
}

int spill(std::size_t n) {
  return each(n, [](std::size_t i) { return opaque(static_cast<int>(i)); }) +
         walk(static_cast<const Wide *>(nullptr), n);
}

} // namespace lib
