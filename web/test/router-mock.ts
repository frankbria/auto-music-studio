/**
 * Mutable Next.js App Router state for tests. `vitest.setup.ts` mocks
 * `next/navigation` to read `pathname` from here; tests set it to drive
 * active-route logic and reset it after each test.
 */
export const routerMock = { pathname: "/" }
