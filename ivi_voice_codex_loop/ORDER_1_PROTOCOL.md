# Order-1 Protocol

This protocol is the default operating contract for IVI-layered conversations and loop execution.

## Single objective

Produce new coherent structure each turn: create or improve relational objects in the IVI grid that are:

- intent-aligned (human-relevant),
- potential-preserving (no premature collapse),
- novelty-producing (non-repetitive),
- formally-groundable (Lean-addressable).

## Invariants (must all hold per iteration)

1. **Intent invariant (Layer 1)**
   - The turn advances a concrete human aim.
2. **Potential invariant (Layer 2)**
   - Keep at least two viable continuations before selecting one.
3. **Novelty invariant (Layer 3)**
   - Add at least one new triangle `(S, D, E)` or strictly improve one existing triangle.
4. **Formal invariant (Layer 4)**
   - Emit or update at least one Lean-addressable artifact (stub, theorem target, or proof obligation).

If any invariant fails, iteration is incomplete.

## Execution cycle

1. **Ingest**
   - Parse input into goal signal, constraints, and open degrees of freedom.
2. **Potential expansion**
   - Generate two or more candidate derivation paths.
3. **Relational closure**
   - Select path with novelty pressure and create/update `(S, D, E, T)`.
4. **Formalization**
   - Patch Lean artifact linked to `E`.
5. **Reflection**
   - Report what changed, why it is non-repetitive, and what remains underdetermined.

## Required artifacts per iteration

- `S`: normalized statement node
- `D`: derivation node with rule + premise/conclusion links
- `E`: equation/Lean node with stable name
- `T`: triangle linking `(S, D, E)`
- Lean delta: inserted/replaced formal block
- Trace delta: anti-collapse trace update

## Selection rule

Use this weighted score when choosing among candidates:

`Score = 0.4 * IntentFit + 0.3 * Novelty + 0.2 * Coherence + 0.1 * FormalReadiness`

Prefer higher novelty and reject near-duplicates unless formal readiness is substantially improved.

## Standard turn output format

1. Goal advanced
2. Candidates considered (2+)
3. Chosen path + reason
4. Created/updated IDs: `S, D, E, T`
5. Lean artifact emitted
6. Newly enabled next action

## Reference phrase

In chat, saying **"Order-1 Protocol"** means: follow this document as the active interaction contract.
