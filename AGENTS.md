# Working in this repo

This is a public, open-source project, and the people building it also use it
at their day jobs. That's where most of its examples come from, so private
detail drifts in easily: a ticket number in a test fixture, an internal
hostname in a doc, a real product bug used as sample data, the company named
in a commit message. Once it's pushed, it's public and stays in the history.

So everything that lands here should make sense to someone who has never heard
of any of our employers. Code, tests, docs, commit messages, PR titles and
descriptions, and review comments all count. When an example would be more
convincing with real detail, invent a neutral one instead. Deployment
specifics belong in an overlay or notes kept outside the repo; `deploy/k8s` is
the generic base those build on.

Two checks back this up, both reading a private list of terms kept outside the
repo (`scripts/check_private_terms.py` explains where):

- `pre-commit install` adds hooks that check staged changes and commit
  messages.
- Before publishing a PR title or description, with `gh pr create` or
  `gh pr edit`, check the exact text first, because CI only sees it after it's
  public:

      python3 scripts/check_private_terms.py --text "PR description" < body.md

CI runs the same check on every PR and push, but by then the text is already
out, so treat a CI failure as a leak to clean up, not a near miss.
