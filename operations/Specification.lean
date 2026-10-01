/- Protocol model for operations.control. Evidence predicates are inputs backed by
   runtime checks, not proofs of Docker, PostgreSQL, MongoDB or Python behavior. -/
namespace Operations
inductive Phase where
  | ready | draining | backedUp | candidate | uncertain | recovering | validated
  deriving DecidableEq

structure State where
  phase : Phase
  owner : Option Nat
  gateOpen : Bool
  backupVerified : Bool
  validationVerified : Bool
  deriving DecidableEq

def initial : State := ⟨.ready, none, true, false, false⟩

inductive Step (actor : Nat) : State → State → Prop where
  | begin (s) (idle : s.phase = .ready) (free : s.owner = none) :
      Step actor s ⟨.draining, some actor, false, false, false⟩
  | backup (s) (held : s.owner = some actor) (phase : s.phase = .draining) :
      Step actor s ⟨.backedUp, some actor, false, true, false⟩
  | launch (s) (held : s.owner = some actor) (phase : s.phase = .backedUp)
      (evidence : s.backupVerified = true) :
      Step actor s ⟨.candidate, some actor, false, true, false⟩
  | validate (s) (held : s.owner = some actor) (phase : s.phase = .candidate)
      (backup : s.backupVerified = true) :
      Step actor s ⟨.validated, some actor, false, true, true⟩
  | interrupt (s) (held : s.owner = some actor) :
      Step actor s {s with phase := .uncertain, gateOpen := false, validationVerified := false}
  | reconcile (s) (held : s.owner = some actor) (phase : s.phase = .uncertain)
      (evidence : s.backupVerified = true) :
      Step actor s ⟨.recovering, some actor, false, true, false⟩
  | restored (s) (held : s.owner = some actor) (phase : s.phase = .recovering)
      (backup : s.backupVerified = true) :
      Step actor s ⟨.validated, some actor, false, true, true⟩
  | recoverBeforeBackup (s) (held : s.owner = some actor)
      (phase : s.phase = .uncertain) (notLaunched : s.backupVerified = false) :
      Step actor s ⟨.validated, some actor, false, false, true⟩
  | finish (s) (held : s.owner = some actor) (phase : s.phase = .validated)
      (evidence : s.validationVerified = true) :
      Step actor s ⟨.ready, none, true, s.backupVerified, true⟩

def Safe (s : State) : Prop :=
  (s.gateOpen = true → s.phase = .ready ∧ s.owner = none) ∧
  (s.phase = .candidate ∨ s.phase = .recovering → s.backupVerified = true) ∧
  (s.phase = .uncertain → s.gateOpen = false)

inductive Reachable : State → Prop where
  | initial : Reachable initial
  | next {s t actor} : Reachable s → Step actor s t → Reachable t

theorem initial_safe : Safe initial := by simp [Safe, initial]

theorem preserves_safe {s t actor} (_safe : Safe s) (step : Step actor s t) : Safe t := by
  cases step <;> simp_all [Safe]

theorem reachable_safe {s} (reachable : Reachable s) : Safe s := by
  induction reachable with
  | initial => exact initial_safe
  | next _ step ih => exact preserves_safe ih step

theorem destructive_requires_verified_backup {s} (reachable : Reachable s)
    (phase : s.phase = .candidate ∨ s.phase = .recovering) : s.backupVerified = true :=
  (reachable_safe reachable).2.1 phase

theorem uncertain_blocks_ingress {s} (reachable : Reachable s)
    (phase : s.phase = .uncertain) : s.gateOpen = false :=
  (reachable_safe reachable).2.2 phase

theorem no_other_owner_step {s t actor other} (held : s.owner = some other)
    (different : actor ≠ other) : ¬ Step actor s t := by
  intro step
  cases step <;> simp_all

theorem no_blind_launch_after_interruption {s t actor}
    (uncertain : s.phase = .uncertain) (step : Step actor s t) : t.phase ≠ .candidate := by
  cases step <;> simp_all
end Operations
#print axioms Operations.initial_safe
#print axioms Operations.preserves_safe
#print axioms Operations.reachable_safe
#print axioms Operations.destructive_requires_verified_backup
#print axioms Operations.uncertain_blocks_ingress
#print axioms Operations.no_other_owner_step
#print axioms Operations.no_blind_launch_after_interruption
