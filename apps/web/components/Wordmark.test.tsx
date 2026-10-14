import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { Wordmark } from "@/components/Wordmark";

// The one render test in this bite: it holds the jsdom environment, the JSX
// transform, the `@/` alias and the jest-dom matchers together.
it("renders the mark with the product's name as its accessible name", () => {
  render(<Wordmark />);
  expect(screen.getByRole("img", { name: "hax" })).toBeInTheDocument();
});
