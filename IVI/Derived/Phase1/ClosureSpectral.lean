/-
IVI/Derived/Phase1/ClosureSpectral.lean

Minimal Phase-1 scaffolding for:
- project / relift gauge selection,
- closure over a concrete GridState,
- an abstract closure-linearization eigen interface,
- a spinor carrier with rInf (∞) and iZero (0),
- and band/gauge-break hooks.

This module is intentionally abstract and self-contained.
-/

namespace IVI

universe u v w

abbrev ISet (α : Type u) := α → Prop

def ISubset {α : Type u} (a b : ISet α) : Prop :=
  ∀ x, a x → b x

def IStrictSubset {α : Type u} (a b : ISet α) : Prop :=
  ISubset a b ∧ ∃ x, b x ∧ ¬ a x

/- -------------------------------------------------------------------------- -/
/- 0) Minimal closure/collapse placeholders (replace with core imports later). -/
/- -------------------------------------------------------------------------- -/

variable {Node : Type u} {Level : Type v}

structure NextShellWitness (Node : Type u) (Level : Type v) where
  admissible : Prop

structure TriangleClosureAttempt (Node : Type u) (Level : Type v) where
  prev : ISet Node
  next : ISet Node
  nextWitness : NextShellWitness Node Level

structure TriangleCollapseWitness (Node : Type u) (Level : Type v) where
  selection : Nat
  support : ISet Node

abbrev CollapseSelection := Nat

def matchesSelection (w : TriangleCollapseWitness Node Level) (sel : CollapseSelection) : Prop :=
  w.selection = sel

def StrictRefines (a : TriangleClosureAttempt Node Level) : Prop :=
  IStrictSubset a.prev a.next

/- -------------------------------------------------------------------------- -/
/- 1) Grid state + closure operator.                                          -/
/- -------------------------------------------------------------------------- -/

variable (Payload : Type w)

structure GridState (Node : Type u) (Level : Type v) (Payload : Type w) where
  attempt : TriangleClosureAttempt Node Level
  payload : Payload

structure GridClosure (Node : Type u) (Level : Type v) (Payload : Type w) where
  close : GridState Node Level Payload → GridState Node Level Payload
  idempotent : ∀ s, close (close s) = close s

namespace GridClosure

variable {Payload : Type w}

theorem close_close (c : GridClosure Node Level Payload) (s : GridState Node Level Payload) :
    c.close (c.close s) = c.close s :=
  c.idempotent s

end GridClosure

/- -------------------------------------------------------------------------- -/
/- 2) Projection / relift interfaces.                                         -/
/- -------------------------------------------------------------------------- -/

structure ClassicalFrame (Node : Type u) (Level : Type v) where
  selection : CollapseSelection
  witness : TriangleCollapseWitness Node Level

def ClassicalFrame.support (f : ClassicalFrame Node Level) : ISet Node :=
  f.witness.support

structure GridProjection (Node : Type u) (Level : Type v) (Payload : Type w) where
  project : GridState Node Level Payload → ClassicalFrame Node Level

structure GridRelift (Node : Type u) (Level : Type v) (Payload : Type w) where
  relift : ClassicalFrame Node Level → Payload → GridState Node Level Payload

def ReliftProjectCoherent
    {Payload : Type w}
    (p : GridProjection Node Level Payload)
    (l : GridRelift Node Level Payload) : Prop :=
  ∀ (f : ClassicalFrame Node Level) (x : Payload),
    (p.project (l.relift f x)).selection = f.selection

/- -------------------------------------------------------------------------- -/
/- 2b) Canonical matrix-loop morphisms: close -> project -> relift.            -/
/- -------------------------------------------------------------------------- -/

structure MatrixLoopStep (Node : Type u) (Level : Type v) (Payload : Type w) where
  closeOp : GridClosure Node Level Payload
  projectOp : GridProjection Node Level Payload
  reliftOp : GridRelift Node Level Payload

def matrixLoopStep
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload)
    (s : GridState Node Level Payload) : GridState Node Level Payload :=
  let sClosed := loop.closeOp.close s
  let frame := loop.projectOp.project sClosed
  loop.reliftOp.relift frame sClosed.payload

def matrixLoopStepN
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload)
    : Nat → GridState Node Level Payload → GridState Node Level Payload
  | 0, s => s
  | n + 1, s => matrixLoopStep loop (matrixLoopStepN loop n s)

def CollapseWitnessValid (f : ClassicalFrame Node Level) : Prop :=
  matchesSelection f.witness f.selection

def MatrixLoopSelectionCoherent
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload) : Prop :=
  ReliftProjectCoherent loop.projectOp loop.reliftOp

def MatrixLoopRefinementProgress
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload)
    (s : GridState Node Level Payload) : Prop :=
  StrictRefines (loop.closeOp.close s).attempt

def MatrixLoopStepCoherent
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload)
    (s : GridState Node Level Payload) : Prop :=
  let sClosed := loop.closeOp.close s
  let frame := loop.projectOp.project sClosed
  MatrixLoopRefinementProgress loop s ∧ CollapseWitnessValid frame

theorem matrixLoopSelection_fromRelift
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload)
    (hSel : MatrixLoopSelectionCoherent loop)
    (f : ClassicalFrame Node Level)
    (x : Payload) :
    (loop.projectOp.project (loop.reliftOp.relift f x)).selection = f.selection :=
  hSel f x

/- -------------------------------------------------------------------------- -/
/- 3) Abstract linearization/eigen interface.                                 -/
/- -------------------------------------------------------------------------- -/

structure TangentFiber (𝕂 : Type u) where
  Tangent : Type u
  instAdd : Add Tangent
  instSMul : SMul 𝕂 Tangent

attribute [instance] TangentFiber.instAdd
attribute [instance] TangentFiber.instSMul

structure ClosureLinearization (𝕂 : Type u) (Node : Type u) (Level : Type v) (Payload : Type w) where
  fiber : TangentFiber 𝕂
  dclose : GridState Node Level Payload → fiber.Tangent → fiber.Tangent

def NoumenalFeigenbaum
    (𝕂 : Type u)
    {Payload : Type w}
    (c : GridClosure Node Level Payload)
    (d : ClosureLinearization 𝕂 Node Level Payload)
    (δ : 𝕂) : Prop :=
  ∃ (s : GridState Node Level Payload) (ψ : d.fiber.Tangent),
    c.close s = s ∧ d.dclose s ψ = δ • ψ

/- -------------------------------------------------------------------------- -/
/- 4) Refinement spinor: rInf ↔ ∞, iZero ↔ 0.                                -/
/- -------------------------------------------------------------------------- -/

structure RefinementSpinor (𝕂 : Type u) where
  rInf : 𝕂
  iZero : 𝕂

namespace RefinementSpinor

variable {𝕂 : Type u}

instance [Mul 𝕂] : SMul 𝕂 (RefinementSpinor 𝕂) where
  smul a ψ := { rInf := a * ψ.rInf, iZero := a * ψ.iZero }

instance [Add 𝕂] : Add (RefinementSpinor 𝕂) where
  add ψ φ := { rInf := ψ.rInf + φ.rInf, iZero := ψ.iZero + φ.iZero }

instance [Zero 𝕂] : Zero (RefinementSpinor 𝕂) where
  zero := { rInf := 0, iZero := 0 }

def toScalar [Add 𝕂] (ψ : RefinementSpinor 𝕂) : 𝕂 :=
  ψ.rInf + ψ.iZero

end RefinementSpinor

/- -------------------------------------------------------------------------- -/
/- 5) Band hooks for gauge-breaking interfaces.                               -/
/- -------------------------------------------------------------------------- -/

variable (ConnSet : Type u)

structure BandMeasurement where
  bandMeasure : ConnSet → Nat

structure BandPredicates (m : BandMeasurement ConnSet) where
  oneThirdBand : ConnSet → Prop
  dftFftCrossing : ConnSet → Prop
  ellipticBand : ConnSet → Prop

structure BandWitness (ConnSet : Type u) where
  conn : ConnSet
  active : Prop

structure HasBandWitness
    (Node : Type u)
    (Level : Type v)
    (Payload : Type w)
    (ConnSet : Type u) where
  getBand : GridState Node Level Payload → Option (BandWitness ConnSet)

/- -------------------------------------------------------------------------- -/
/- 6) Spinor-tangent version of the eigen claim.                              -/
/- -------------------------------------------------------------------------- -/

def NoumenalFeigenbaumSpinor
    (𝕂 : Type u)
    {Payload : Type w}
    (c : GridClosure Node Level Payload)
    (d : ClosureLinearization 𝕂 Node Level Payload)
    (δ : 𝕂) : Prop :=
  ∃ (s : GridState Node Level Payload) (ψ : d.fiber.Tangent),
    c.close s = s ∧ d.dclose s ψ = δ • ψ

/- -------------------------------------------------------------------------- -/
/- 7) Lightweight behavioral adapter (bridge to external step semantics).      -/
/- -------------------------------------------------------------------------- -/

structure BehavioralAdapter (Node : Type u) (Level : Type v) (Payload : Type w) where
  X : Type w
  Step : X → X → Prop
  encode : GridState Node Level Payload → X

def MatrixLoopStepRel
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload)
    (s s' : GridState Node Level Payload) : Prop :=
  s' = matrixLoopStep loop s

def AdapterSound
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload)
    (A : BehavioralAdapter Node Level Payload) : Prop :=
  ∀ s, A.Step (A.encode s) (A.encode (matrixLoopStep loop s))

theorem adapter_step_sound
    {Payload : Type w}
    (loop : MatrixLoopStep Node Level Payload)
    (A : BehavioralAdapter Node Level Payload)
    (h : AdapterSound loop A)
    (s : GridState Node Level Payload) :
    A.Step (A.encode s) (A.encode (matrixLoopStep loop s)) :=
  h s

end IVI
