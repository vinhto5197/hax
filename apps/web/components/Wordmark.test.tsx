import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { Wordmark } from "@/components/Wordmark";

it("renders the mark with the product's name as its accessible name", () => {
  render(<Wordmark />);
  expect(screen.getByRole("img", { name: "Hax" })).toBeInTheDocument();
});
