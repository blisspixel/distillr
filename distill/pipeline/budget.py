"""Budget enforcement exceptions shared by pipeline cost controls."""

# pyright: strict


class BudgetExceededError(Exception):
    """A run's recorded spend crossed its budget ceiling.

    Budgeted direct cloud attempts normally refuse on a conservative projection
    before contact. This post-record guard remains for usage that exceeds its
    admitted bound and for provider workflows without a hard dollar control.
    Recorded spend stays on the ledger so callers can stop without hiding it.
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
