// Polynomials with non-negative coefficients over named symbols: the cost
// algebra. Symbols are non-negative, so the coefficient-wise maximum of two
// polynomials bounds the larger of their values (join).
#ifndef VC_POLY_H
#define VC_POLY_H

#include <map>
#include <optional>
#include <string>

namespace vc {

/// The trip count of a loop, or cost of a call, with no bound.
inline constexpr const char *Unbounded = "?";

using Monomial = std::map<std::string, unsigned>;

class Poly {
public:
  Poly() = default;
  static Poly constant(double C);
  static Poly symbol(const std::string &Name);
  /// A capacity known only by its value, as a template argument is inside an
  /// instantiation: `#value`, until `name` gives it a symbol.
  static Poly capacity(double Value);
  /// Each `#value` replaced by the one symbol of `Values` with that value, or
  /// by the value itself when there is no such symbol or more than one.
  Poly name(const std::map<std::string, std::optional<double>> &Values) const;
  /// Sums of products of non-negative integers, symbols, `s^k`, `log2(s)`
  /// and parentheses; a qualified name keeps its last `::` component.
  static std::optional<Poly> parse(const std::string &Text);
  /// An upper bound of log2 of this polynomial: log2 of the coefficient sum
  /// plus the degree-weighted `log2(s)` of each symbol (symbols are >= 1).
  Poly log2() const;

  Poly operator+(const Poly &O) const;
  Poly operator*(const Poly &O) const;
  Poly &operator+=(const Poly &O) { return *this = *this + O; }
  /// Coefficient-wise maximum: an upper bound of max(this, O).
  Poly join(const Poly &O) const;
  /// The smaller of two bounds of the same quantity, by total degree, then by
  /// the sum of coefficients.
  static const Poly &tighter(const Poly &A, const Poly &B);

  bool zero() const { return Terms.empty(); }
  std::optional<double> constantValue() const;
  unsigned degree(const std::string &Sym) const;
  unsigned totalDegree() const;
  double coefficientSum() const;
  const std::map<Monomial, double> &terms() const { return Terms; }
  std::string str() const;

private:
  void add(const Monomial &M, double C);
  std::map<Monomial, double> Terms;
};

} // namespace vc

#endif
