# Test-Driven Development (TDD) Rules

## Core TDD Workflow

When making any production code changes, you MUST follow this strict TDD cycle:

### 1. Write Failing Tests First
- **ALWAYS** write failing test(s) before writing or modifying production code
- Run the tests to verify they fail for the right reason
- Tests should clearly specify the expected behavior

### 2. Implement Minimal Code
- Write the minimum amount of production code needed to make the tests pass
- Do not add functionality that isn't covered by tests
- Run tests to verify they pass

### 3. Refactor
- Once tests are passing, refactor to improve code quality
- Look for opportunities to:
  - Remove duplication
  - Improve naming and clarity
  - Simplify complex logic
  - Improve structure and organization
- Run tests after each refactoring to ensure nothing breaks
- Only complete the task after refactoring is done

## Mandatory Practices

- **No production code without tests**: Never write or modify production code without corresponding failing tests first
- **Run tests frequently**: Run the test suite after each change to verify behavior
- **Test naming**: Use descriptive test names that explain what behavior is being tested
- **One test at a time**: Focus on making one test pass at a time
- **Commit after green**: Only commit when tests are passing

## Test Organization

- Place tests in appropriate test files (e.g., `test_*.py` or `*_test.py` for Python)
- Use clear arrange-act-assert (AAA) pattern in tests
- Keep tests independent and isolated
- Mock external dependencies appropriately

## Exceptions

The only time you may skip writing tests first:
- Exploratory spike code explicitly marked as temporary
- User explicitly requests to skip tests (must be confirmed)

## Pull Request Requirements

Before creating a pull request, you MUST:

1. **All tests must pass**: Run the full test suite and ensure 100% of tests pass
2. **Lint must pass**: Run the linter and fix all linting errors and warnings
3. **No uncommitted changes**: Ensure all changes are committed

### Pre-PR Checklist

- [ ] All tests passing
- [ ] Linting passing (no errors or warnings)
- [ ] Code has been refactored
- [ ] Changes are committed

Do not create a pull request until all items in the checklist are complete.

## Red-Green-Refactor Reminder

🔴 **RED**: Write a failing test
🟢 **GREEN**: Make it pass with minimal code
🔵 **REFACTOR**: Improve the code while keeping tests green

## GitHub PR Comments

To fetch PR comments (including review comments from Copilot):

```bash
# Get review comments (code-level comments)
gh api repos/pixeltree/council_feeds/pulls/{PR_NUMBER}/comments

# Get issue comments (general PR discussion)
gh api repos/pixeltree/council_feeds/issues/{PR_NUMBER}/comments
```

Use the API method instead of `gh pr view --comments` when you need structured comment data.
