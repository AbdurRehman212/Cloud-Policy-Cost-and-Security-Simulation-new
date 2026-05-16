# Project Mandates: Execution Pipeline

All tasks within this repository must strictly adhere to the following 5-step execution pipeline. No steps may be skipped. If any step fails, execution must stop, and a report must be provided.

## 1. Analyze
- Perform deep research into the codebase.
- Identify all affected files, symbols, and dependencies.
- Empirically reproduce any reported bugs or verify current behavior.

## 2. Plan
- Draft a technical strategy using `enter_plan_mode` for complex tasks.
- Define the specific implementation approach.
- Outline the testing strategy to verify the changes.

## 3. Implement
- Apply surgical code changes.
- Adhere strictly to existing architectural patterns and styles.
- Ensure type safety and idiomatic quality.

## 4. Test
- Add or update automated tests (unit, integration, or e2e).
- Verify the specific logic changed.

## 5. Validate
- Run the full project validation suite (build, lint, type-check).
- Perform runtime verification to ensure system-wide integrity.
- Confirm that the UI and backend are in sync.
