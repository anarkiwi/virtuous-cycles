#include "program.h"

#include "llvm/Support/GlobPattern.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <functional>

namespace vc {

CostRef Cost::leaf(Poly P) {
  auto C = std::make_shared<Cost>();
  C->P = std::move(P);
  return C;
}

static CostRef combine(Cost::Kind K, CostRef A, CostRef B) {
  if (A->K == Cost::Leaf && B->K == Cost::Leaf)
    return Cost::leaf(K == Cost::Sum ? A->P + B->P : A->P.join(B->P));
  if (K == Cost::Sum && A->zero())
    return B;
  if (B->zero())
    return A;
  auto C = std::make_shared<Cost>();
  C->K = K;
  for (const CostRef &X : {A, B}) {
    if (X->K == K)
      C->Kids.insert(C->Kids.end(), X->Kids.begin(), X->Kids.end());
    else
      C->Kids.push_back(X);
  }
  return C;
}

CostRef Cost::sum(CostRef A, CostRef B) { return combine(Sum, A, B); }
CostRef Cost::join(CostRef A, CostRef B) { return combine(Join, A, B); }

CostRef Cost::scale(const Poly &P, CostRef E) {
  if (E->K == Leaf || P.zero())
    return leaf(P * E->P);
  if (P.constantValue() == 1.0)
    return E;
  auto C = std::make_shared<Cost>();
  C->K = Scale;
  C->P = P;
  C->Kids = {E};
  return C;
}

CostRef Cost::call(std::string Usr, std::string Callee, Site At, bool Virtual,
                   bool Pure) {
  auto C = std::make_shared<Cost>();
  C->K = Call;
  C->Usr = std::move(Usr);
  C->Callee = std::move(Callee);
  C->At = std::move(At);
  C->Virtual = Virtual;
  C->Pure = Pure;
  return C;
}

void Program::symbol(const std::string &Name, std::optional<double> Value) {
  auto [It, New] = Symbols.emplace(Name, Value);
  if (New || !Value || It->second == Value || Conflicts.count(Name))
    return;
  if (It->second)
    Conflicts.insert(Name);
  It->second = Conflicts.count(Name) ? std::nullopt : Value;
}

void Program::merge(Program &&O) {
  Functions.merge(O.Functions);
  for (auto &[K, V] : O.Overriders)
    Overriders[K].merge(V);
  Conflicts.merge(O.Conflicts);
  for (auto &[K, V] : O.Symbols)
    symbol(K, V);
  for (const std::string &K : Conflicts)
    Symbols[K].reset();
}

std::vector<std::string> Program::candidates(const Cost &C) const {
  if (!C.Virtual)
    return {C.Usr};
  std::vector<std::string> Out;
  std::set<std::string> Seen{C.Usr};
  std::vector<std::string> Work{C.Usr};
  if (!C.Pure)
    Out.push_back(C.Usr);
  while (!Work.empty()) {
    auto It = Overriders.find(Work.back());
    Work.pop_back();
    if (It == Overriders.end())
      continue;
    for (const std::string &O : It->second)
      if (Seen.insert(O).second) {
        Work.push_back(O);
        Out.push_back(O);
      }
  }
  return Out;
}

void Program::edges(const Cost &C, std::set<std::string> &Out) const {
  if (C.K == Cost::Call)
    for (const std::string &U : candidates(C))
      Out.insert(U);
  for (const CostRef &K : C.Kids)
    edges(*K, Out);
}

Poly Program::eval(const Cost &C, const std::set<std::string> &Scc,
                   std::vector<LedgerEntry> &Ledger, const std::string &Owner) {
  switch (C.K) {
  case Cost::Leaf:
    return C.P;
  case Cost::Scale:
    return C.P * eval(*C.Kids[0], Scc, Ledger, Owner);
  case Cost::Sum:
  case Cost::Join: {
    Poly R;
    for (const CostRef &K : C.Kids) {
      Poly V = eval(*K, Scc, Ledger, Owner);
      R = C.K == Cost::Sum ? R + V : R.join(V);
    }
    return R;
  }
  case Cost::Call:
    break;
  }
  auto Cands = candidates(C);
  if (Cands.empty()) {
    Ledger.push_back({"virtual", Owner,
                      "virtual call to " + C.Callee + " has no overrider",
                      C.At});
    return Poly::symbol(Unbounded);
  }
  Poly R;
  for (const std::string &U : Cands) {
    if (Scc.count(U))
      continue;
    auto It = Resolved.find(U);
    if (It != Resolved.end()) {
      R = R.join(It->second);
      continue;
    }
    Ledger.push_back({"external", Owner,
                      "call to " + C.Callee + " whose body is not analysed",
                      C.At});
    R = R.join(Poly::symbol(Unbounded));
  }
  return R;
}

std::vector<Entry> Program::resolve(const std::vector<std::string> &Patterns,
                                    std::string &Error) {
  std::map<std::string, std::set<std::string>> Graph;
  for (const auto &[U, F] : Functions)
    edges(*F.Body, Graph[U]);

  // Tarjan's strongly connected components; each is complete once its
  // callees' are, so components are resolved in the order they close.
  std::map<std::string, unsigned> Index, Low;
  std::vector<std::string> Stack;
  std::set<std::string> OnStack;
  unsigned Next = 0;
  std::function<void(const std::string &)> Visit = [&](const std::string &U) {
    Index[U] = Low[U] = Next++;
    Stack.push_back(U);
    OnStack.insert(U);
    for (const std::string &V : Graph[U]) {
      if (!Functions.count(V))
        continue;
      if (!Index.count(V)) {
        Visit(V);
        Low[U] = std::min(Low[U], Low[V]);
      } else if (OnStack.count(V)) {
        Low[U] = std::min(Low[U], Index[V]);
      }
    }
    if (Low[U] != Index[U])
      return;
    std::set<std::string> Scc;
    std::string V;
    do {
      V = Stack.back();
      Stack.pop_back();
      OnStack.erase(V);
      Scc.insert(V);
    } while (V != U);
    bool Cyclic = Scc.size() > 1 || Graph[U].count(U);
    Poly Local;
    std::optional<Poly> Bound;
    for (const std::string &M : Scc) {
      Function &F = Functions[M];
      Poly P = eval(*F.Body, Scc, F.Ledger, F.Name);
      if (!Cyclic) {
        Resolved[M] = P;
        return;
      }
      Local += P;
      if (F.Recursion)
        Bound = Bound ? Bound->join(*F.Recursion) : *F.Recursion;
    }
    if (!Bound) {
      Bound = Poly::symbol(Unbounded);
      for (const std::string &M : Scc) {
        Function &F = Functions[M];
        F.Ledger.push_back(
            {"recursion", F.Name, "recursive call with no bound", F.At});
      }
    }
    for (const std::string &M : Scc)
      Resolved[M] = *Bound * Local;
  };
  for (const auto &[U, F] : Functions)
    if (!Index.count(U))
      Visit(U);

  std::vector<Entry> Out;
  for (const std::string &Pat : Patterns) {
    auto Glob = llvm::GlobPattern::create(Pat, 4096);
    if (!Glob) {
      Error = "bad entry pattern " + Pat + ": " + toString(Glob.takeError());
      return {};
    }
    Entry E{Pat, {}, {}, {}};
    std::vector<std::string> Work;
    for (const auto &[U, F] : Functions)
      if (Glob->match(F.Name) || Glob->match(F.Plain)) {
        E.Functions.push_back(F.Name);
        E.Cost = E.Cost.join(Resolved[U].name(Symbols));
        Work.push_back(U);
      }
    if (Work.empty()) {
      Error = "entry " + Pat + " matches no analysed function";
      return {};
    }
    std::set<std::string> Seen(Work.begin(), Work.end());
    std::set<std::tuple<Site, std::string, std::string>> Dedup;
    while (!Work.empty()) {
      std::string U = Work.back();
      Work.pop_back();
      for (const LedgerEntry &L : Functions[U].Ledger)
        if (Dedup.insert({L.At, L.Kind, L.Reason}).second)
          E.Ledger.push_back(L);
      for (const std::string &V : Graph[U])
        if (Functions.count(V) && Seen.insert(V).second)
          Work.push_back(V);
    }
    std::sort(E.Functions.begin(), E.Functions.end());
    std::sort(E.Ledger.begin(), E.Ledger.end(),
              [](const LedgerEntry &A, const LedgerEntry &B) {
                return std::tie(A.At, A.Kind, A.Reason) <
                       std::tie(B.At, B.Kind, B.Reason);
              });
    Out.push_back(std::move(E));
  }
  return Out;
}

void writeJson(std::ostream &OS, const Program &P,
               const std::vector<Entry> &Entries) {
  std::set<std::string> Used;
  for (const Entry &E : Entries)
    for (const auto &[M, C] : E.Cost.terms())
      for (const auto &[S, X] : M) {
        llvm::StringRef R(S);
        if (R.consume_front("log2(") && R.consume_back(")"))
          Used.insert(R.str());
        else if (S != Unbounded)
          Used.insert(S);
      }
  std::string Text;
  llvm::raw_string_ostream SS(Text);
  llvm::json::OStream J(SS, 1);
  J.object([&] {
    J.attribute("version", 1);
    J.attribute("unbounded_symbol", Unbounded);
    J.attributeObject("symbols", [&] {
      for (const std::string &S : Used) {
        auto It = P.Symbols.find(S);
        if (It != P.Symbols.end() && It->second)
          J.attribute(S, *It->second);
        else
          J.attribute(S, nullptr);
      }
    });
    J.attributeObject("entries", [&] {
      for (const Entry &E : Entries)
        J.attributeObject(E.Pattern, [&] {
          J.attributeArray("functions", [&] {
            for (const std::string &F : E.Functions)
              J.value(F);
          });
          J.attribute("polynomial", E.Cost.str());
          J.attributeArray("terms", [&] {
            for (const auto &[M, C] : E.Cost.terms())
              J.object([&] {
                J.attribute("coefficient", C);
                J.attributeObject("powers", [&] {
                  for (const auto &[S, X] : M)
                    J.attribute(S, X);
                });
              });
          });
          J.attributeObject("degree", [&] {
            std::set<std::string> Syms;
            for (const auto &[M, C] : E.Cost.terms())
              for (const auto &[S, X] : M)
                Syms.insert(S);
            for (const std::string &S : Syms)
              J.attribute(S, E.Cost.degree(S));
          });
          J.attributeArray("ledger", [&] {
            for (const LedgerEntry &L : E.Ledger)
              J.object([&] {
                J.attribute("kind", L.Kind);
                J.attribute("function", L.Function);
                J.attribute("file", L.At.File);
                J.attribute("line", L.At.Line);
                J.attribute("column", L.At.Column);
                J.attribute("reason", L.Reason);
              });
          });
        });
    });
  });
  SS.flush();
  OS << Text << "\n";
}

} // namespace vc
