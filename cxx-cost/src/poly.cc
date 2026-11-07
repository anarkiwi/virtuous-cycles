#include "poly.h"

#include "llvm/ADT/StringRef.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <set>
#include <vector>

namespace vc {

static std::string number(double C) {
  char Buf[32];
  if (C == std::floor(C) && C < 1e15)
    std::snprintf(Buf, sizeof Buf, "%.0f", C);
  else
    std::snprintf(Buf, sizeof Buf, "%g", C);
  return Buf;
}

Poly Poly::constant(double C) {
  Poly P;
  P.add({}, C);
  return P;
}

Poly Poly::symbol(const std::string &Name) {
  Poly P;
  P.add({{Name, 1}}, 1);
  return P;
}

Poly Poly::capacity(double Value) { return symbol("#" + number(Value)); }

Poly Poly::name(
    const std::map<std::string, std::optional<double>> &Values) const {
  std::map<double, std::string> Unique;
  std::set<double> Shared;
  for (const auto &[S, V] : Values)
    if (V && !Unique.emplace(*V, S).second)
      Shared.insert(*V);
  Poly R;
  for (const auto &[M, C] : Terms) {
    Poly T = constant(C);
    for (const auto &[S, E] : M) {
      llvm::StringRef Sym(S);
      bool Log = Sym.consume_front("log2(") && Sym.consume_back(")");
      Poly F = symbol(S);
      if (Sym.consume_front("#")) {
        double V = std::stod(Sym.str());
        auto It = Unique.find(V);
        F = It == Unique.end() || Shared.count(V) ? constant(V)
                                                  : symbol(It->second);
        if (Log)
          F = F.log2();
      }
      for (unsigned K = 0; K < E; ++K)
        T = T * F;
    }
    R += T;
  }
  return R;
}

void Poly::add(const Monomial &M, double C) {
  if (C > 0)
    Terms[M] += C;
}

Poly Poly::operator+(const Poly &O) const {
  Poly R = *this;
  for (const auto &[M, C] : O.Terms)
    R.add(M, C);
  return R;
}

Poly Poly::operator*(const Poly &O) const {
  Poly R;
  for (const auto &[MA, CA] : Terms)
    for (const auto &[MB, CB] : O.Terms) {
      Monomial M = MA;
      for (const auto &[S, E] : MB)
        M[S] += E;
      R.add(M, CA * CB);
    }
  return R;
}

Poly Poly::join(const Poly &O) const {
  Poly R = *this;
  for (const auto &[M, C] : O.Terms) {
    double &Slot = R.Terms[M];
    Slot = std::max(Slot, C);
  }
  return R;
}

const Poly &Poly::tighter(const Poly &A, const Poly &B) {
  auto Key = [](const Poly &P) {
    return std::make_pair(P.totalDegree(), P.coefficientSum());
  };
  return Key(B) < Key(A) ? B : A;
}

std::optional<double> Poly::constantValue() const {
  if (Terms.empty())
    return 0.0;
  if (Terms.size() == 1 && Terms.begin()->first.empty())
    return Terms.begin()->second;
  return std::nullopt;
}

unsigned Poly::degree(const std::string &Sym) const {
  unsigned D = 0;
  for (const auto &[M, C] : Terms) {
    auto It = M.find(Sym);
    if (It != M.end())
      D = std::max(D, It->second);
  }
  return D;
}

unsigned Poly::totalDegree() const {
  unsigned D = 0;
  for (const auto &[M, C] : Terms) {
    unsigned T = 0;
    for (const auto &[S, E] : M)
      T += E;
    D = std::max(D, T);
  }
  return D;
}

double Poly::coefficientSum() const {
  double S = 0;
  for (const auto &[M, C] : Terms)
    S += C;
  return S;
}

Poly Poly::log2() const {
  if (auto C = constantValue())
    return constant(*C > 1 ? std::ceil(std::log2(*C)) : 0);
  Poly R = constant(std::ceil(std::log2(std::max(coefficientSum(), 1.0))));
  std::map<std::string, unsigned> Deg;
  for (const auto &[M, C] : Terms)
    for (const auto &[S, E] : M)
      Deg[S] = std::max(Deg[S], E);
  for (const auto &[S, E] : Deg)
    R += constant(E) * symbol(S == Unbounded ? S : "log2(" + S + ")");
  return R;
}

std::string Poly::str() const {
  if (Terms.empty())
    return "0";
  std::vector<std::pair<Monomial, double>> Order(Terms.begin(), Terms.end());
  auto Total = [](const Monomial &M) {
    unsigned T = 0;
    for (const auto &[S, E] : M)
      T += E;
    return T;
  };
  std::stable_sort(Order.begin(), Order.end(), [&](auto &A, auto &B) {
    return Total(A.first) > Total(B.first);
  });
  std::string Out;
  for (const auto &[M, C] : Order) {
    if (!Out.empty())
      Out += " + ";
    std::string Term = M.empty() || C != 1 ? number(C) : "";
    for (const auto &[S, E] : M) {
      if (!Term.empty())
        Term += "*";
      Term += S;
      if (E > 1)
        Term += "^" + std::to_string(E);
    }
    Out += Term;
  }
  return Out;
}

namespace {

class Parser {
public:
  explicit Parser(const std::string &T) : Text(T) {}

  std::optional<Poly> run() {
    auto P = sum();
    skip();
    if (!P || Pos != Text.size())
      return std::nullopt;
    return P;
  }

private:
  void skip() {
    while (Pos < Text.size() && std::isspace((unsigned char)Text[Pos]))
      ++Pos;
  }
  bool eat(char C) {
    skip();
    if (Pos < Text.size() && Text[Pos] == C) {
      ++Pos;
      return true;
    }
    return false;
  }
  static bool identStart(char C) {
    return std::isalpha((unsigned char)C) || C == '_';
  }
  static bool identChar(char C) {
    return std::isalnum((unsigned char)C) || C == '_';
  }
  std::string ident() {
    std::string Name;
    while (true) {
      size_t Start = Pos;
      while (Pos < Text.size() && identChar(Text[Pos]))
        ++Pos;
      Name += Text.substr(Start, Pos - Start);
      size_t Sep = Text.compare(Pos, 2, "::") == 0   ? 2
                   : Text.compare(Pos, 2, "->") == 0 ? 2
                   : Text.compare(Pos, 1, ".") == 0  ? 1
                                                     : 0;
      if (!Sep || Pos + Sep >= Text.size() || !identStart(Text[Pos + Sep]))
        break;
      if (Text[Pos] == ':')
        Name.clear();
      else
        Name += Text.substr(Pos, Sep);
      Pos += Sep;
    }
    return Name;
  }
  std::optional<Poly> sum() {
    auto P = product();
    while (P && eat('+')) {
      auto Q = product();
      if (!Q)
        return std::nullopt;
      *P += *Q;
    }
    return P;
  }
  std::optional<Poly> product() {
    auto P = factor();
    while (P && eat('*')) {
      auto Q = factor();
      if (!Q)
        return std::nullopt;
      P = *P * *Q;
    }
    return P;
  }
  std::optional<Poly> factor() {
    skip();
    if (Pos >= Text.size())
      return std::nullopt;
    std::optional<Poly> Base;
    char C = Text[Pos];
    if (eat('(')) {
      Base = sum();
      if (!Base || !eat(')'))
        return std::nullopt;
    } else if (std::isdigit((unsigned char)C)) {
      size_t End;
      double V = std::stod(Text.substr(Pos), &End);
      Pos += End;
      while (Pos < Text.size() && std::strchr("uUlL", Text[Pos]))
        ++Pos;
      Base = Poly::constant(V);
    } else if (eat('?')) {
      Base = Poly::symbol(Unbounded);
    } else if (identStart(C)) {
      std::string Name = ident();
      if (Name == "log2" && eat('(')) {
        auto Arg = sum();
        if (!Arg || !eat(')'))
          return std::nullopt;
        Base = Arg->log2();
      } else {
        Base = Poly::symbol(Name);
      }
    } else {
      return std::nullopt;
    }
    if (eat('^')) {
      skip();
      size_t Start = Pos;
      while (Pos < Text.size() && std::isdigit((unsigned char)Text[Pos]))
        ++Pos;
      if (Start == Pos)
        return std::nullopt;
      Poly R = Poly::constant(1);
      for (unsigned K = std::stoul(Text.substr(Start, Pos - Start)); K; --K)
        R = R * *Base;
      Base = R;
    }
    return Base;
  }

  const std::string &Text;
  size_t Pos = 0;
};

} // namespace

std::optional<Poly> Poly::parse(const std::string &Text) {
  return Parser(Text).run();
}

} // namespace vc
