"""Budget enforcement exceptions shared by pipeline cost controls."""

# pyright: strict


class BudgetExceededError(Exception):
    """A run's recorded spend crossed its budget ceiling.

    Raised after the crossing call is recorded. Its spend already happened and
    must stay on the ledger. Callers catch this to stop cleanly: artifacts
    written so far are durable and verifier-gated, and convergent reruns pick
    up where the run stopped.
    """

    def __init__(self, spent: float, budget: float):
        self.spent = spent
        self.budget = budget
        cap = f"${budget:.4f}" if budget < 0.01 else f"${budget:.2f}"
        super().__init__(f"spend ${spent:.4f} exceeded the {cap} budget")


class ProjectedBudgetExceededError(BudgetExceededError):
    """A credible pre-run estimate exceeds the configured workflow budget."""

    def __init__(self, projected: float, budget: float):
        self.spent = projected
        self.projected = projected
        self.budget = budget
        cap = f"${budget:.4f}" if budget < 0.01 else f"${budget:.2f}"
        Exception.__init__(
            self,
            f"projected spend ${projected:.4f} exceeds the {cap} budget before the run starts",
        )
