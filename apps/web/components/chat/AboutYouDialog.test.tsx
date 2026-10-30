import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AboutYouDialog } from "@/components/chat/AboutYouDialog";
import type { ProfileOut } from "@/lib/profileApi";

const { getProfile, saveProfile } = vi.hoisted(() => ({
  getProfile: vi.fn<() => Promise<ProfileOut>>(),
  saveProfile: vi.fn<(about: string) => Promise<ProfileOut>>(),
}));
vi.mock("@/lib/profileApi", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/profileApi")>(
      "@/lib/profileApi",
    );
  return { ...actual, getProfile, saveProfile };
});

const HELP =
  "Tell hax about yourself: what you do, what you know, how you like answers. hax reads this in every conversation.";
const LOAD_FAILED = "Couldn't load your note. Close and try again.";
const SAVE_FAILED = "Couldn't save. Try again.";
const SAVED = "I teach chemistry; keep answers short.";

type Held<T> = {
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
};

function hold<T>(mock: {
  mockImplementationOnce: (fn: () => Promise<T>) => unknown;
}): Held<T> {
  const held = {} as Held<T>;
  mock.mockImplementationOnce(
    () =>
      new Promise<T>((resolve, reject) => {
        held.resolve = resolve;
        held.reject = reject;
      }),
  );
  return held;
}

beforeEach(() => {
  getProfile.mockResolvedValue({ about: SAVED });
  saveProfile.mockImplementation(async (about: string) => ({
    about: about.trim() || null,
  }));
});

function dialog() {
  return screen.queryByRole("dialog", { name: "About you" });
}
function textarea() {
  return screen.getByRole("textbox", { name: "About you" });
}
function saveButton() {
  return screen.getByRole("button", { name: "Save" });
}
function cancelButton() {
  return screen.getByRole("button", { name: "Cancel" });
}

function renderDialog() {
  const onClose = vi.fn();
  render(<AboutYouDialog onClose={onClose} />);
  return onClose;
}

async function renderLoaded(about: string | null = SAVED) {
  getProfile.mockResolvedValueOnce({ about });
  const onClose = renderDialog();
  await vi.waitFor(() => expect(textarea()).toBeEnabled());
  return onClose;
}

function type(value: string) {
  fireEvent.change(textarea(), { target: { value } });
}

function pressEscape(target: Element = textarea()) {
  // fireEvent returns false when a handler called preventDefault().
  return fireEvent.keyDown(target, { key: "Escape", code: "Escape" });
}

describe("AboutYouDialog", () => {
  it("is a modal dialog titled About you with the help line, the textarea, Save and Cancel", async () => {
    await renderLoaded();
    const el = dialog();
    expect(el).toBeInTheDocument();
    expect(el).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText(HELP)).toBeInTheDocument();
    expect(textarea()).toBeInTheDocument();
    expect(saveButton()).toBeInTheDocument();
    expect(cancelButton()).toBeInTheDocument();
  });

  it("has no maxLength on the textarea", async () => {
    await renderLoaded();
    expect(textarea()).not.toHaveAttribute("maxlength");
  });

  it("keeps the textarea and Save disabled until the load returns, then shows the saved note", async () => {
    const load = hold<ProfileOut>(getProfile);
    renderDialog();
    expect(textarea()).toBeDisabled();
    expect(saveButton()).toBeDisabled();

    await act(async () => load.resolve({ about: SAVED }));

    expect(textarea()).toBeEnabled();
    expect(textarea()).toHaveValue(SAVED);
    expect(screen.getByText(`${SAVED.length} / 1000`)).toBeInTheDocument();
  });

  it("starts empty when there is no saved note", async () => {
    await renderLoaded(null);
    expect(textarea()).toHaveValue("");
    expect(screen.getByText("0 / 1000")).toBeInTheDocument();
  });

  it("shows the load-failure line and keeps the textarea and Save disabled when the load fails", async () => {
    const load = hold<ProfileOut>(getProfile);
    renderDialog();
    await act(async () => load.reject(new Error("API 500")));

    expect(screen.getByText(LOAD_FAILED)).toBeInTheDocument();
    expect(textarea()).toBeDisabled();
    expect(saveButton()).toBeDisabled();
  });

  it("puts the cursor in the textarea once loaded", async () => {
    await renderLoaded();
    await vi.waitFor(() => expect(textarea()).toHaveFocus());
  });

  it("counts characters as code points, so an emoji counts once", async () => {
    await renderLoaded(null);
    type("😀");
    expect(screen.getByText("1 / 1000")).toBeInTheDocument();
    type("ab😀👍");
    expect(screen.getByText("4 / 1000")).toBeInTheDocument();
  });

  it("counts the trimmed text", async () => {
    await renderLoaded(null);
    type("   hello   ");
    expect(screen.getByText("5 / 1000")).toBeInTheDocument();
  });

  it("disables Save while the trimmed text equals the saved note", async () => {
    await renderLoaded();
    expect(saveButton()).toBeDisabled();
    type(`  ${SAVED}\n `);
    expect(saveButton()).toBeDisabled();
    type(`${SAVED} more`);
    expect(saveButton()).toBeEnabled();
  });

  it("disables Save over 1000 characters", async () => {
    await renderLoaded(null);
    type("x".repeat(1001));
    expect(screen.getByText("1001 / 1000")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("allows exactly 1000 characters plus trailing whitespace", async () => {
    await renderLoaded(null);
    type(`${"x".repeat(1000)} `);
    expect(screen.getByText("1000 / 1000")).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();
  });

  it("allows 1000 emoji, which are 2000 UTF-16 units", async () => {
    await renderLoaded(null);
    type("😀".repeat(1000));
    expect(screen.getByText("1000 / 1000")).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();
  });

  it("saves the text and closes on success", async () => {
    const onClose = await renderLoaded(null);
    type("I write Go for a living.");
    fireEvent.click(saveButton());
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(saveProfile).toHaveBeenCalledTimes(1);
    expect(saveProfile.mock.calls[0][0].trim()).toBe(
      "I write Go for a living.",
    );
  });

  it("saves an empty text when the note is cleared", async () => {
    const onClose = await renderLoaded();
    type("");
    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(saveProfile.mock.calls[0][0].trim()).toBe("");
  });

  it("shows the save error and stays open when the save is rejected", async () => {
    saveProfile.mockRejectedValueOnce(new Error("API 500"));
    const onClose = await renderLoaded(null);
    type("something new");
    fireEvent.click(saveButton());

    expect(await screen.findByText(SAVE_FAILED)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(dialog()).toBeInTheDocument();
    expect(textarea()).toHaveValue("something new");
  });

  it("shows the save error and stays open when the server answers 422", async () => {
    const actual =
      await vi.importActual<typeof import("@/lib/profileApi")>(
        "@/lib/profileApi",
      );
    saveProfile.mockImplementation(actual.saveProfile);
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "too long" }), {
            status: 422,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    const onClose = await renderLoaded(null);
    type("text the server refuses");
    fireEvent.click(saveButton());

    expect(await screen.findByText(SAVE_FAILED)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(dialog()).toBeInTheDocument();
  });

  it("while a save is in flight, the textarea is read-only and Save, Cancel and Escape do nothing", async () => {
    const save = hold<ProfileOut>(saveProfile);
    const onClose = await renderLoaded(null);
    type("in flight");
    fireEvent.click(saveButton());

    await vi.waitFor(() => expect(textarea()).toHaveAttribute("readonly"));
    fireEvent.click(saveButton());
    fireEvent.click(cancelButton());
    expect(pressEscape()).toBe(false);
    expect(saveProfile).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
    expect(dialog()).toBeInTheDocument();

    await act(async () => save.resolve({ about: "in flight" }));
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("reports a failed save even after Cancel and Escape were pressed during it", async () => {
    const save = hold<ProfileOut>(saveProfile);
    const onClose = await renderLoaded(null);
    type("will fail");
    fireEvent.click(saveButton());
    fireEvent.click(cancelButton());
    pressEscape();

    await act(async () => save.reject(new Error("API 500")));
    expect(await screen.findByText(SAVE_FAILED)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does nothing on a tap on the backdrop", async () => {
    const onClose = await renderLoaded(null);
    type("keep me");
    const panel = dialog()!;
    // The backdrop is the dialog's own full-screen layer: whatever element
    // around the dialog, outside it, receives a tap beside the panel.
    const outside: Element[] = [document.body];
    let node: Element | null = panel.parentElement;
    while (node && node !== document.body) {
      outside.push(node);
      node = node.parentElement;
    }
    for (const sibling of Array.from(panel.parentElement?.children ?? [])) {
      if (sibling !== panel) outside.push(sibling);
    }
    for (const el of outside) {
      fireEvent.pointerDown(el);
      fireEvent.mouseDown(el);
      fireEvent.click(el);
    }

    expect(onClose).not.toHaveBeenCalled();
    expect(dialog()).toBeInTheDocument();
    expect(textarea()).toHaveValue("keep me");
  });

  it("a press on the backdrop is marked defaultPrevented, so focus stays inside the dialog", async () => {
    await renderLoaded();
    const backdrop = dialog()!.parentElement!;
    expect(fireEvent.mouseDown(backdrop)).toBe(false);
  });

  it("Escape cancels and is marked defaultPrevented", async () => {
    const onClose = await renderLoaded();
    type("unsaved");
    expect(pressEscape()).toBe(false);
    expect(onClose).toHaveBeenCalled();
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it("Cancel closes without saving", async () => {
    const onClose = await renderLoaded();
    type("unsaved");
    fireEvent.click(cancelButton());
    expect(onClose).toHaveBeenCalled();
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it("Escape is marked defaultPrevented while loading", () => {
    hold<ProfileOut>(getProfile);
    renderDialog();
    expect(pressEscape(dialog()!)).toBe(false);
  });

  it("Escape is marked defaultPrevented after a failed load", async () => {
    const load = hold<ProfileOut>(getProfile);
    renderDialog();
    await act(async () => load.reject(new Error("API 500")));
    expect(pressEscape(dialog()!)).toBe(false);
  });

  it("Escape is marked defaultPrevented after a failed save", async () => {
    saveProfile.mockRejectedValueOnce(new Error("API 500"));
    await renderLoaded(null);
    type("x");
    fireEvent.click(saveButton());
    await screen.findByText(SAVE_FAILED);
    expect(pressEscape()).toBe(false);
  });
});

describe("AboutYouDialog focus", () => {
  it("Tab from Save wraps to the textarea and Shift+Tab from the textarea wraps to Save", async () => {
    await renderLoaded();
    type(`${SAVED} more`);
    expect(saveButton()).toBeEnabled();

    act(() => saveButton().focus());
    expect(fireEvent.keyDown(saveButton(), { key: "Tab" })).toBe(false);
    expect(textarea()).toHaveFocus();

    expect(
      fireEvent.keyDown(textarea(), { key: "Tab", shiftKey: true }),
    ).toBe(false);
    expect(saveButton()).toHaveFocus();
  });

  it("skips a disabled Save, so Tab from Cancel wraps to the textarea", async () => {
    await renderLoaded();
    expect(saveButton()).toBeDisabled();

    act(() => cancelButton().focus());
    expect(fireEvent.keyDown(cancelButton(), { key: "Tab" })).toBe(false);
    expect(textarea()).toHaveFocus();

    expect(
      fireEvent.keyDown(textarea(), { key: "Tab", shiftKey: true }),
    ).toBe(false);
    expect(cancelButton()).toHaveFocus();
  });

  describe("on close", () => {
    let outside: HTMLElement[] = [];

    function addAccountButton(visible: boolean) {
      const button = document.createElement("button");
      button.setAttribute("aria-label", "Account menu");
      Object.defineProperty(button, "offsetParent", {
        configurable: true,
        get: () => (visible ? document.body : null),
      });
      document.body.appendChild(button);
      outside.push(button);
      return button;
    }

    function addMessageBox() {
      const box = document.createElement("textarea");
      box.setAttribute("aria-label", "Message");
      document.body.appendChild(box);
      outside.push(box);
      return box;
    }

    afterEach(() => {
      for (const el of outside) el.remove();
      outside = [];
    });

    async function renderThenUnmount() {
      getProfile.mockResolvedValueOnce({ about: SAVED });
      const { unmount } = render(<AboutYouDialog onClose={vi.fn()} />);
      await vi.waitFor(() => expect(textarea()).toBeEnabled());
      unmount();
    }

    it("returns focus to a visible Account menu button", async () => {
      const button = addAccountButton(true);
      addMessageBox();
      await renderThenUnmount();
      await vi.waitFor(() => expect(document.activeElement).toBe(button));
    });

    it("falls back to the Message box when there is no Account menu button", async () => {
      const box = addMessageBox();
      await renderThenUnmount();
      await vi.waitFor(() => expect(document.activeElement).toBe(box));
    });

    it("falls back to the Message box when the Account menu button is hidden", async () => {
      addAccountButton(false);
      const box = addMessageBox();
      await renderThenUnmount();
      await vi.waitFor(() => expect(document.activeElement).toBe(box));
    });
  });
});

