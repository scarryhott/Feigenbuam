/-
IVI update: collapse is NOT absorbing.

There is no strict split into "never collapse" vs "linear forever" regimes.
At each stage, evolution can remain complex, collapse, or re-superpose.

Equality is modeled as branching behavioral complexity rather than point identity.
-/

namespace IVI

universe u u0 uI uObs

/- Abstract "state" type. -/
variable {X : Type u}

/- 0-side (compactification / contraction view). -/
variable {X0 : Type u0}

/- inf-side (projection / expansion view). -/
variable {XInf : Type uI}

/- Identity content observable via closure. -/
variable {Obs : Type uObs}

abbrev Pred (α : Type _) := α → Prop

/-- Poles used when collapse decides 0 vs inf. -/
inductive Pole : Type
  | zero
  | inf
deriving DecidableEq, Repr

/-- Mutable phase marker (can change over time). -/
inductive Phase : Type
  | potential
  | collapsed
deriving DecidableEq, Repr

/--
Core comb + time interface.
- compact/project: incomplete views
- close: completion of incompleteness (comb closure)
- refine: complexity-chooses-itself move
- collapse: branch-selection move
- resuperpose: lift from collapsed back to potential complexity
- linearStep: optional deterministic move in collapsed phase
- phase: mutable label (not assumed stable)
-/
structure CombTimeOps (X : Type u) (X0 : Type u0) (XInf : Type uI) (Obs : Type uObs) where
  compact    : X → X0
  project    : X → XInf
  close      : X0 → XInf → Obs

  refine     : X → X
  collapse   : X → Pole → X
  resuperpose : X → X
  linearStep : X → X
  phase      : X → Phase

namespace CombTimeOps

variable (ops : CombTimeOps X X0 XInf Obs)

/-- Comb closure observation. -/
def obs (x : X) : Obs :=
  ops.close (ops.compact x) (ops.project x)

/-- Nondeterministic one-step evolution. -/
inductive Step : X → X → Prop
  | refine   (x : X) : Step x (ops.refine x)
  | collapse (x : X) (p : Pole) : Step x (ops.collapse x p)
  | resuperpose (x : X) : Step x (ops.resuperpose x)
  | linear   (x : X) (hx : ops.phase x = Phase.collapsed) : Step x (ops.linearStep x)

attribute [simp] Step.refine Step.collapse Step.resuperpose

/--
Indeterminate-at-x: at least two distinct next states exist from x.
-/
def IndeterminateAt (x : X) : Prop :=
  ∃ y1 y2 : X, y1 ≠ y2 ∧ Step ops x y1 ∧ Step ops x y2

/-- A run is an infinite sequence of states with valid one-step transitions. -/
structure Run where
  state : Nat → X
  stepOK : ∀ n : Nat, Step ops (state n) (state (n + 1))

/-- Initial state of a run. -/
def Run.start (r : Run ops) : X :=
  r.state 0

def Run.obsStream (r : Run ops) : Nat → Obs :=
  fun n => ops.obs (r.state n)

/-- All runs starting from x (branching superposition of futures). -/
def RunsFrom (x : X) : Pred (Run ops) :=
  fun r => r.start = x

/-- Behavior predicate: observation streams reachable from x via some run. -/
def Beh (x : X) : Pred (Nat → Obs) :=
  fun s => ∃ r : Run ops, r.start = x ∧ s = r.obsStream (ops := ops)

/-- Superposition/complexity equality by full branching behavior. -/
def EqSup (x y : X) : Prop :=
  ∀ s : Nat → Obs, Beh ops x s ↔ Beh ops y s

/-- States reachable from x in exactly n steps. -/
def ReachN : Nat → X → Pred X
  | 0, x => fun y => y = x
  | n + 1, x => fun y => ∃ z, ReachN n x z ∧ Step ops z y

/--
Finite trace relation over indeterminate evolution.
This is an explicit path semantics for "the choice is indeterminate":
multiple Step constructors can extend a trace at each depth.
-/
inductive Trace : Nat → X → X → Prop
  | nil (x : X) : Trace 0 x x
  | cons {n : Nat} {x y z : X} :
      Step ops x y →
      Trace n y z →
      Trace (n + 1) x z

/--
Trace-based complexity equality under indeterminate branching.
For any equal-depth traces from x and y, endpoint closure observations agree.
-/
def EqCIndet (x y : X) : Prop :=
  ∀ n x' y',
    Trace ops n x x' →
    Trace ops n y y' →
    ops.obs x' = ops.obs y'

/-- Depth-n observation frontier from x. -/
def ObsSetN (n : Nat) (x : X) : Pred Obs :=
  fun o => ∃ y, ReachN ops n x y ∧ ops.obs y = o

/-- Omega-approximate equality by matching finite-depth observation frontiers. -/
def EqSupOmega (x y : X) : Prop :=
  ∀ n : Nat, ∀ o : Obs, ObsSetN ops n x o ↔ ObsSetN ops n y o

/-- Optional schema: collapse marks collapsed phase. -/
def CollapseMarksCollapsed : Prop :=
  ∀ x : X, ∀ p : Pole, ops.phase (ops.collapse x p) = Phase.collapsed

/-- Optional schema: resuperpose marks potential phase. -/
def ResuperposeMarksPotential : Prop :=
  ∀ x : X, ops.phase (ops.resuperpose x) = Phase.potential

/-- Behavioral narrowing by transformation f at state x. -/
def BehNarrowerAfter (f : X → X) (x : X) : Prop :=
  ∀ s : Nat → Obs, Beh ops (f x) s → Beh ops x s

/-- Behavioral widening by transformation f at state x. -/
def BehWiderAfter (f : X → X) (x : X) : Prop :=
  ∀ s : Nat → Obs, Beh ops x s → Beh ops (f x) s

/-- Optional schema: collapse narrows behavior space. -/
def CollapseNarrows : Prop :=
  ∀ x : X, ∀ p : Pole, BehNarrowerAfter ops (fun z => ops.collapse z p) x

/-- Optional schema: resuperpose widens behavior space. -/
def ResuperposeWidens : Prop :=
  ∀ x : X, BehWiderAfter ops ops.resuperpose x

section Laws

theorem EqSup_refl (x : X) : EqSup ops x x := by
  intro s
  exact Iff.rfl

theorem EqSup_symm {x y : X} : EqSup ops x y → EqSup ops y x := by
  intro h s
  exact (h s).symm

theorem EqSup_trans {x y z : X} : EqSup ops x y → EqSup ops y z → EqSup ops x z := by
  intro h1 h2 s
  exact Iff.trans (h1 s) (h2 s)

theorem EqSup_equiv : Equivalence (EqSup ops) :=
  ⟨EqSup_refl (ops := ops), by intro a b; exact EqSup_symm (ops := ops), by intro a b c; exact EqSup_trans (ops := ops)⟩

theorem EqSupOmega_refl (x : X) : EqSupOmega ops x x := by
  intro n o
  exact Iff.rfl

theorem EqSupOmega_symm {x y : X} : EqSupOmega ops x y → EqSupOmega ops y x := by
  intro h n o
  exact (h n o).symm

theorem EqSupOmega_trans {x y z : X} : EqSupOmega ops x y → EqSupOmega ops y z → EqSupOmega ops x z := by
  intro h1 h2 n o
  exact Iff.trans (h1 n o) (h2 n o)

theorem EqSupOmega_equiv : Equivalence (EqSupOmega ops) :=
  ⟨EqSupOmega_refl (ops := ops), by intro a b; exact EqSupOmega_symm (ops := ops), by intro a b c; exact EqSupOmega_trans (ops := ops)⟩

end Laws

theorem indeterminate_of_distinct_refine_collapse
  (x : X)
  (p : Pole)
  (hneq : ops.refine x ≠ ops.collapse x p) :
  IndeterminateAt ops x := by
  refine ⟨ops.refine x, ops.collapse x p, hneq, ?_, ?_⟩
  · exact Step.refine (ops := ops) x
  · exact Step.collapse (ops := ops) x p

end CombTimeOps

end IVI
