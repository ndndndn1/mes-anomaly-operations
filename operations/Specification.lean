namespace ReleaseRehearsal
inductive Outcome where
  | pending | committed | rolledBack
  deriving DecidableEq
structure State where
  outcome : Outcome
  originalPreserved : Bool
  schemaValidated : Bool
  deriving DecidableEq

def finish (ok : Bool) : State :=
  if ok then ⟨.committed, false, true⟩ else ⟨.rolledBack, true, false⟩

theorem failure_preserves : (finish false).originalPreserved = true := by decide
theorem failure_not_commit : (finish false).outcome ≠ .committed := by decide
theorem commit_requires_validation (ok : Bool) :
    (finish ok).outcome = .committed → (finish ok).schemaValidated = true := by
  cases ok <;> simp [finish]
end ReleaseRehearsal
#print axioms ReleaseRehearsal.failure_preserves
#print axioms ReleaseRehearsal.failure_not_commit
#print axioms ReleaseRehearsal.commit_requires_validation
