// A header this clang rejects, as FixedPoints' in-class constexpr constants are.
static_assert(sizeof(int) == 0, "third-party header");
inline int fine() { return 1; }
inline int broken() { return nope(); }
