import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library unmounts between tests only when it finds a global
// afterEach; test globals are off here, so the suite registers it.
afterEach(cleanup);
