import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ModelSelect } from "@/components/chat/ModelSelect";

function options() {
  const select = screen.getByRole("combobox", { name: "Model" });
  return within(select).getAllByRole("option") as HTMLOptionElement[];
}

function optionLabelled(label: string) {
  const option = options().find((o) => o.textContent?.trim() === label);
  if (!option) throw new Error(`no option labelled ${label}`);
  return option;
}

describe("ModelSelect hints", () => {
  it("gives every option a non-empty title and keeps the labels", () => {
    render(<ModelSelect value="" onChange={() => {}} />);
    const all = options();
    expect(all.map((o) => o.textContent?.trim())).toEqual([
      "Default",
      "Haiku",
      "Sonnet",
      "Opus",
    ]);
    expect(optionLabelled("Default")).toHaveAttribute("value", "");
    for (const option of all) {
      expect(option.getAttribute("title")?.trim()).toBeTruthy();
    }
  });

  it("shows the selected option's hint as a caption that follows the value", () => {
    const { rerender } = render(<ModelSelect value="" onChange={() => {}} />);
    // The options carry their hint as an attribute, not text, so these text
    // queries match only the caption line.
    const defaultHint = optionLabelled("Default").title;
    const opus = optionLabelled("Opus");
    const opusHint = opus.title;
    expect(opusHint).not.toBe(defaultHint);
    expect(screen.getByText(defaultHint)).toBeVisible();
    expect(screen.queryByText(opusHint)).not.toBeInTheDocument();

    rerender(<ModelSelect value={opus.value} onChange={() => {}} />);
    expect(screen.getByText(opusHint)).toBeVisible();
    expect(screen.queryByText(defaultHint)).not.toBeInTheDocument();
  });
});
