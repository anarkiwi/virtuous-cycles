// Annotations read by vc-cxx-cost, and a fixed-capacity container whose
// capacity bounds every loop over it. The annotations are clang attributes,
// so they vanish under any other compiler.
#ifndef VC_COST_H
#define VC_COST_H

#include <array>
#include <cstddef>
#include <utility>

#if defined(__clang__) && __clang_major__ >= 20
#define VC_ANNOTATE(tag, ...) [[clang::annotate(tag, #__VA_ARGS__)]]
#define VC_CAPPED [[clang::annotate("vc::capped")]]
#else
#define VC_ANNOTATE(tag, ...)
#define VC_CAPPED
#endif

/// Before a loop: its trip count, e.g. `VC_BOUND(kMaxBoxes * 2) for (...)`.
#define VC_BOUND(...) VC_ANNOTATE("vc::bound", __VA_ARGS__)
/// Before a loop inside another: the trip count summed over every iteration of
/// the loops around it in the same function (not per iteration), e.g. the
/// notes of all channels when every channel draws on one shared pool.
#define VC_TOTAL(...) VC_ANNOTATE("vc::total", __VA_ARGS__)
/// Like VC_TOTAL, but summed over every execution of the loop in one run of the
/// entry point, however many calls deep: for work that every caller in the run
/// shares, such as a loop over a pool that all of them draw on, in a function
/// that a loop elsewhere calls once per channel. The loop's cost then neither
/// multiplies by the loops around it in its own function nor by those around
/// the calls that reach it. A loop reached from two call sites counts once per
/// site; a call joined with others (a virtual call, VC_TARGETS) or in a
/// recursive cycle is scaled by the loops around it as usual.
#define VC_RUN_TOTAL(...) VC_ANNOTATE("vc::runtotal", __VA_ARGS__)
/// Before a statement: one operation plus the cost of the most expensive of the
/// named functions (globs over qualified names). For a call through a function
/// pointer, `VC_TARGETS(ns::a, ns::b)` names what it can reach.
#define VC_TARGETS(...) VC_ANNOTATE("vc::targets", __VA_ARGS__)
/// Before a statement or a function declaration: its whole cost.
#define VC_COST(...) VC_ANNOTATE("vc::cost", __VA_ARGS__)
/// On a variable, field, parameter or function: an upper bound of its value
/// (an integer) or of its size (a container).
#define VC_SIZE(...) VC_ANNOTATE("vc::size", __VA_ARGS__)
/// On a function in a recursive cycle: how many activations of the cycle one
/// call into it makes at most.
#define VC_RECURSION(...) VC_ANNOTATE("vc::recursion", __VA_ARGS__)
/// On a constant: the symbol it is reported as (default: its own name).
#define VC_SYMBOL(...) VC_ANNOTATE("vc::symbol", __VA_ARGS__)

namespace vc {

/// At most `N` elements; a push past `N` is refused and counted.
template <class T, std::size_t N> class VC_CAPPED Capped {
public:
  bool push_back(T V) {
    if (Size == N) {
      ++Dropped;
      return false;
    }
    Items[Size++] = std::move(V);
    return true;
  }
  void clear() { Size = 0; }
  std::size_t size() const { return Size; }
  std::size_t dropped() const { return Dropped; }
  static constexpr std::size_t capacity() { return N; }
  bool empty() const { return Size == 0; }
  bool full() const { return Size == N; }
  T &operator[](std::size_t I) { return Items[I]; }
  const T &operator[](std::size_t I) const { return Items[I]; }
  T *begin() { return Items.data(); }
  T *end() { return Items.data() + Size; }
  const T *begin() const { return Items.data(); }
  const T *end() const { return Items.data() + Size; }

private:
  std::array<T, N> Items{};
  std::size_t Size = 0, Dropped = 0;
};

} // namespace vc

#endif
