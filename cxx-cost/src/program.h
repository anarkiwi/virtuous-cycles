// Per-function cost summaries over a set of translation units, and their
// composition through the call graph into a polynomial per entry point.
#ifndef VC_PROGRAM_H
#define VC_PROGRAM_H

#include "poly.h"

#include <map>
#include <memory>
#include <optional>
#include <ostream>
#include <set>
#include <string>
#include <vector>

namespace vc {

struct Site {
  std::string File;
  unsigned Line = 0, Column = 0;
  bool operator<(const Site &O) const {
    return std::tie(File, Line, Column) < std::tie(O.File, O.Line, O.Column);
  }
};

/// Something whose cost has no bound: it contributes the `?` symbol.
struct LedgerEntry {
  std::string Kind, Function, Reason;
  Site At;
};

struct Cost;
using CostRef = std::shared_ptr<const Cost>;

/// A cost expression: a polynomial, or sums, joins, scalings and calls whose
/// cost is known only once every translation unit has been read.
struct Cost {
  /// `Hoist` marks a total over every iteration of the loops around it in
  /// its function: scaling by those loops leaves it alone. With `Run` the
  /// total is over the whole run of the entry point, so it also passes up
  /// through calls and the loops around them. `Targets` is the
  /// join of the functions named by `Names` (globs over qualified names).
  enum Kind { Leaf, Sum, Join, Scale, Call, Hoist, Targets } K = Leaf;
  Poly P;
  std::vector<CostRef> Kids;
  // Call: the callee's USR and, for a virtual call, whether the callee itself
  // is pure (its overriders are then the only candidates).
  std::string Usr, Callee;
  bool Virtual = false, Pure = false, Run = false;
  std::vector<std::string> Names;
  Site At;

  static CostRef leaf(Poly P);
  static CostRef sum(CostRef A, CostRef B);
  static CostRef join(CostRef A, CostRef B);
  static CostRef scale(const Poly &P, CostRef E);
  static CostRef call(std::string Usr, std::string Callee, Site At,
                      bool Virtual = false, bool Pure = false);
  static CostRef hoist(CostRef E, bool Run = false);
  static CostRef targets(std::vector<std::string> Names, Site At);
  bool zero() const { return K == Leaf && P.zero(); }
};

struct Function {
  std::string Name, Plain;
  Site At;
  CostRef Body;
  std::vector<LedgerEntry> Ledger;
  std::optional<Poly> Recursion;
  /// A backward goto makes the whole body a loop with no bound.
  bool Loops = false;
};

struct Entry {
  std::string Pattern;
  std::vector<std::string> Functions;
  Poly Cost;
  std::vector<LedgerEntry> Ledger;
  /// Every function the entry reaches and the cost of each, by name; only
  /// filled when asked for.
  std::vector<std::pair<std::string, Poly>> Breakdown;
};

class Program {
public:
  std::map<std::string, Function> Functions;
  std::map<std::string, std::set<std::string>> Overriders;
  std::map<std::string, std::optional<double>> Symbols;
  /// Symbols given two different values: their value is unknown.
  std::set<std::string> Conflicts;

  /// Record a symbol and its value if known; two different values make it
  /// unknown.
  void symbol(const std::string &Name, std::optional<double> Value);
  /// Take `O`'s summaries; a function already present keeps its own.
  void merge(Program &&O);
  /// Each pattern's cost: the join of the functions it names, and the ledger
  /// of everything they reach. An error names a pattern matching nothing.
  std::vector<Entry> resolve(const std::vector<std::string> &Patterns,
                             std::string &Error, bool Breakdown = false);

private:
  /// A cost split into what the loops around it scale and what they do not.
  struct Parts {
    /// What the loops around it scale; what only the loops of its own
    /// function leave alone; what no loop around it, in any function, scales.
    Poly Scaled, Hoisted, Run;
    Poly total() const { return Scaled + Hoisted + Run; }
  };
  Parts eval(const Cost &C, const std::set<std::string> &Scc,
             std::vector<LedgerEntry> &Ledger, const std::string &Owner);
  std::vector<std::string> candidates(const Cost &C) const;
  void edges(const Cost &C, std::set<std::string> &Out) const;
  std::map<std::string, Parts> Resolved;
};

void writeJson(std::ostream &OS, const Program &P,
               const std::vector<Entry> &Entries);
/// The merged summaries before composition, as JSON: functions with indices
/// into a shared table of cost nodes, overriders, symbols and conflicts.
void writeIr(std::ostream &OS, const Program &P,
             const std::vector<std::string> &Patterns, bool Breakdown);

} // namespace vc

#endif
