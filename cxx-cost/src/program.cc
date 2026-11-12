#include "program.h"

#include "llvm/Support/GlobPattern.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <functional>
#include <unordered_map>

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

CostRef Cost::hoist(CostRef E, bool Run) {
  if (E->zero())
    return E;
  auto C = std::make_shared<Cost>();
  C->K = Hoist;
  C->Run = Run;
  C->Kids = {E};
  return C;
}

CostRef Cost::targets(std::vector<std::string> Names, Site At) {
  auto C = std::make_shared<Cost>();
  C->K = Targets;
  C->Names = std::move(Names);
  C->At = std::move(At);
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
  if (C.K == Cost::Targets) {
    std::vector<std::string> Out;
    for (const std::string &Pat : C.Names) {
      auto Glob = llvm::GlobPattern::create(Pat, 4096);
      if (!Glob) {
        llvm::consumeError(Glob.takeError());
        continue;
      }
      for (const auto &[U, F] : Functions)
        if (Glob->match(F.Name) || Glob->match(F.Plain))
          Out.push_back(U);
    }
    std::sort(Out.begin(), Out.end());
    Out.erase(std::unique(Out.begin(), Out.end()), Out.end());
    return Out;
  }
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
  if (C.K == Cost::Call || C.K == Cost::Targets)
    for (const std::string &U : candidates(C))
      Out.insert(U);
  for (const CostRef &K : C.Kids)
    edges(*K, Out);
}

Program::Parts Program::eval(const Cost &C, const std::set<std::string> &Scc,
                             std::vector<LedgerEntry> &Ledger,
                             const std::string &Owner) {
  switch (C.K) {
  case Cost::Leaf:
    return {C.P, {}, {}};
  case Cost::Scale: {
    Parts V = eval(*C.Kids[0], Scc, Ledger, Owner);
    return {C.P * V.Scaled, V.Hoisted, V.Run};
  }
  case Cost::Hoist: {
    Parts V = eval(*C.Kids[0], Scc, Ledger, Owner);
    if (C.Run)
      return {{}, {}, V.total()};
    return {{}, V.Scaled + V.Hoisted, V.Run};
  }
  case Cost::Sum: {
    Parts R;
    for (const CostRef &K : C.Kids) {
      Parts V = eval(*K, Scc, Ledger, Owner);
      R.Scaled = R.Scaled + V.Scaled;
      R.Hoisted = R.Hoisted + V.Hoisted;
      R.Run = R.Run + V.Run;
    }
    return R;
  }
  case Cost::Join: {
    // The larger branch is not known to be the same one for every part, so a
    // join keeps its whole cost under the loops around it.
    Poly R;
    for (const CostRef &K : C.Kids)
      R = R.join(eval(*K, Scc, Ledger, Owner).total());
    return {R, {}, {}};
  }
  case Cost::Call:
  case Cost::Targets:
    break;
  }
  auto Cands = candidates(C);
  if (Cands.empty()) {
    if (C.K == Cost::Targets) {
      std::string Names;
      for (const std::string &N : C.Names)
        Names += (Names.empty() ? "" : ", ") + N;
      Ledger.push_back({"annotation", Owner,
                        "VC_TARGETS names no analysed function: " + Names,
                        C.At});
    } else {
      Ledger.push_back({"virtual", Owner,
                        "virtual call to " + C.Callee + " has no overrider",
                        C.At});
    }
    return {Poly::symbol(Unbounded), {}, {}};
  }
  // One callee keeps its run-wide total apart; several are joined, which
  // keeps that total under the loops around the call too.
  std::vector<Parts> Known;
  for (const std::string &U : Cands) {
    if (Scc.count(U))
      continue;
    auto It = Resolved.find(U);
    if (It != Resolved.end()) {
      Known.push_back(It->second);
      continue;
    }
    Ledger.push_back({"external", Owner,
                      "call to " + C.Callee + " whose body is not analysed",
                      C.At});
    Known.push_back({Poly::symbol(Unbounded), {}, {}});
  }
  if (Known.size() == 1)
    return {Known[0].Scaled + Known[0].Hoisted, {}, Known[0].Run};
  Poly R;
  for (const Parts &K : Known)
    R = R.join(K.total());
  return {R, {}, {}};
}

std::vector<Entry> Program::resolve(const std::vector<std::string> &Patterns,
                                    std::string &Error, bool Breakdown) {
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
      Parts Split = eval(*F.Body, Scc, F.Ledger, F.Name);
      if (!Cyclic) {
        // A function's own totals end here; its run-wide one goes on up.
        Resolved[M] = {Split.Scaled + Split.Hoisted, {}, Split.Run};
        return;
      }
      Local += Split.total();
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
      Resolved[M] = {*Bound * Local, {}, {}};
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
    Entry E{Pat, {}, {}, {}, {}};
    std::vector<std::string> Work;
    for (const auto &[U, F] : Functions)
      if (Glob->match(F.Name) || Glob->match(F.Plain)) {
        E.Functions.push_back(F.Name);
        E.Cost = E.Cost.join(Resolved[U].total().name(Symbols));
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
    if (Breakdown)
      for (const std::string &U : Seen)
        if (Functions.count(U))
          E.Breakdown.emplace_back(Functions[U].Name,
                                   Resolved[U].total().name(Symbols));
    std::sort(E.Breakdown.begin(), E.Breakdown.end(),
              [](const auto &A, const auto &B) {
                return A.first != B.first ? A.first < B.first
                                          : A.second.str() < B.second.str();
              });
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
          if (!E.Breakdown.empty())
            J.attributeArray("breakdown", [&] {
              for (const auto &[N, C] : E.Breakdown)
                J.object([&] {
                  J.attribute("function", N);
                  J.attribute("polynomial", C.str());
                });
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

static void writeSite(llvm::json::OStream &J, const Site &S) {
  J.array([&] {
    J.value(S.File);
    J.value(S.Line);
    J.value(S.Column);
  });
}

static void writeTerms(llvm::json::OStream &J, const Poly &P) {
  J.array([&] {
    for (const auto &[M, C] : P.terms())
      J.array([&] {
        J.value(C);
        J.object([&] {
          for (const auto &[S, X] : M)
            J.attribute(S, X);
        });
      });
  });
}

void writeIr(std::ostream &OS, const Program &P,
             const std::vector<std::string> &Patterns, bool Breakdown) {
  std::unordered_map<const Cost *, size_t> Index;
  std::vector<const Cost *> Nodes;
  std::function<size_t(const Cost *)> Number = [&](const Cost *C) {
    if (auto It = Index.find(C); It != Index.end())
      return It->second;
    for (const CostRef &K : C->Kids)
      Number(K.get());
    Nodes.push_back(C);
    return Index[C] = Nodes.size() - 1;
  };
  for (const auto &[U, F] : P.Functions)
    Number(F.Body.get());
  static constexpr const char *Kinds[] = {"leaf", "sum",   "join",   "scale",
                                          "call", "hoist", "targets"};
  std::string Text;
  llvm::raw_string_ostream SS(Text);
  llvm::json::OStream J(SS);
  J.object([&] {
    J.attribute("version", 1);
    J.attributeArray("entries", [&] {
      for (const std::string &E : Patterns)
        J.value(E);
    });
    J.attribute("breakdown", Breakdown);
    J.attributeObject("program", [&] {
      J.attributeObject("functions", [&] {
        for (const auto &[U, F] : P.Functions)
          J.attributeObject(U, [&] {
            J.attribute("name", F.Name);
            J.attribute("plain", F.Plain);
            J.attributeBegin("at");
            writeSite(J, F.At);
            J.attributeEnd();
            J.attribute("body", Index.at(F.Body.get()));
            J.attributeArray("ledger", [&] {
              for (const LedgerEntry &L : F.Ledger)
                J.object([&] {
                  J.attribute("kind", L.Kind);
                  J.attribute("function", L.Function);
                  J.attribute("reason", L.Reason);
                  J.attributeBegin("at");
                  writeSite(J, L.At);
                  J.attributeEnd();
                });
            });
            J.attributeBegin("recursion");
            if (F.Recursion)
              writeTerms(J, *F.Recursion);
            else
              J.value(nullptr);
            J.attributeEnd();
            J.attribute("loops", F.Loops);
          });
      });
      J.attributeArray("nodes", [&] {
        for (const Cost *C : Nodes)
          J.object([&] {
            J.attribute("k", Kinds[C->K]);
            if (C->K == Cost::Leaf || C->K == Cost::Scale) {
              J.attributeBegin("p");
              writeTerms(J, C->P);
              J.attributeEnd();
            }
            if (C->K == Cost::Call) {
              J.attribute("usr", C->Usr);
              J.attribute("callee", C->Callee);
              J.attribute("virtual", C->Virtual);
              J.attribute("pure", C->Pure);
            }
            if (C->K == Cost::Hoist)
              J.attribute("run", C->Run);
            if (C->K == Cost::Targets)
              J.attributeArray("names", [&] {
                for (const std::string &N : C->Names)
                  J.value(N);
              });
            if (C->K == Cost::Call || C->K == Cost::Targets) {
              J.attributeBegin("at");
              writeSite(J, C->At);
              J.attributeEnd();
            }
            if (!C->Kids.empty())
              J.attributeArray("kids", [&] {
                for (const CostRef &K : C->Kids)
                  J.value(Index.at(K.get()));
              });
          });
      });
      J.attributeObject("overriders", [&] {
        for (const auto &[U, O] : P.Overriders)
          J.attributeArray(U, [&] {
            for (const std::string &X : O)
              J.value(X);
          });
      });
      J.attributeObject("symbols", [&] {
        for (const auto &[S, V] : P.Symbols)
          if (V)
            J.attribute(S, *V);
          else
            J.attribute(S, nullptr);
      });
      J.attributeArray("conflicts", [&] {
        for (const std::string &S : P.Conflicts)
          J.value(S);
      });
    });
  });
  SS.flush();
  OS << Text << "\n";
}

} // namespace vc
