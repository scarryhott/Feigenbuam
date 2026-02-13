# Potential Transition System (PTS) Spine

This file defines the shared interface that binds all IVI layers into one system.

## Ultimate goal object

Implement a **Potential-to-Act** pipeline where action selection is a theorem-governed refinement of indeterminate potential (0-inf closure), not a primitive collapse.

## Two-axis framing

- **Axis A — Semantics:** what the objects mean.
- **Axis B — Enforcement:** what runtime and Lean can guarantee.

## Layer mapping

1. **Layer 1 (Human loop / classical protocol)**
   - Semantics: intention, dialogue, task decomposition, explanation channel.
   - Enforcement: protocol checks, safety and consistency constraints.
2. **Layer 2 (Born potential core)**
   - Semantics: potential as substrate; Born map as selection law over potential.
   - Enforcement: potential function + weight map interface implementation.
3. **Layer 3 (0-inf closure dynamics)**
   - Semantics: collapse-like outcomes derived from closure/refinement; choice is indeterminate.
   - Enforcement: branching refinement relation and anti-repetition trace discipline.
4. **Layer 4 (Lean formal core)**
   - Semantics: minimal axioms for indeterminacy, closure, and equality-by-refinement.
   - Enforcement: theorem boundary depended on by runtime interfaces.

## PTS interface

For state space `S` and action space `A`:

- `Pot : S x A -> PotVal`
  - Potentiality functional (ordered value, not itself probability).
- `Born : PotVal^A -> Weight^A`
  - Produces selection weights from potential values.
- `Refine : S x A -> S' x Evidence`
  - Closure/refinement transition producing derived evidence.
- `Select : S -> DistLike A`
  - Runtime selection object derived from Born weights.
- `Explain : S x A x Evidence -> Narrative`
  - Layer-1 aligned explanation channel.

## Required cross-layer invariants

1. **Normalization boundary**
   - Born output is normalized and auditable at interface boundaries.
2. **Refinement boundary**
   - Selection must correspond to a valid refinement transition.
3. **Indeterminacy boundary**
   - Multiple valid continuations exist before selection (no forced single next-state map).
4. **Non-repetition boundary**
   - Recent trace pressure penalizes repeated triangle reuse.
5. **Explanation correspondence boundary**
   - Explanations reference actual selected transitions and emitted evidence.

## Acceptance test (minimum integration test)

**Test: nontrivial loop + explanation consistency**

Given a small cyclic environment:

- Layer 2 emits stable Born-derived weights from potential traces.
- Layer 3 emits non-repetitive refinement traces (novelty pressure active).
- Layer 1 explanation cites the selected refinement and its evidence.
- Layer 4 proves at least one invariant used by this run (e.g., normalization or refinement coherence).

If any layer cannot contribute to this test, stack integration is incomplete.

## Repo integration note

- Conversation contract: `ORDER_1_PROTOCOL.md`
- Semantic-enforcement spine: `POTENTIAL_TRANSITION_SYSTEM.md`

In chat, saying **"Order-1 Protocol"** means execution must satisfy both:
1) process contract (`ORDER_1_PROTOCOL.md`), and
2) shared goal object/interface (`POTENTIAL_TRANSITION_SYSTEM.md`).
