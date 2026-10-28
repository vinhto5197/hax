import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AboutYouProvider,
  useAboutYou,
} from "@/components/chat/AboutYouProvider";
import type {
  getProfile as GetProfileFn,
  saveProfile as SaveProfileFn,
} from "@/lib/profileApi";

// The signed-in member is read through next-auth's useSession; a test
// switches members by reassigning `session.current` and rerendering.
const { session, getSession, getProfile, saveProfile } = vi.hoisted(() => ({
  session: {
    current: null as null | {
      user: { id: string; email: string; name: string };
    },
  },
  getSession: vi.fn(),
  getProfile: vi.fn<typeof GetProfileFn>(),
  saveProfile: vi.fn<typeof SaveProfileFn>(),
}));
vi.mock("next-auth/react", () => ({
  useSession: () => ({
    data: session.current,
    status: session.current ? "authenticated" : "unauthenticated",
  }),
  getSession,
}));
vi.mock("@/lib/profileApi", () => ({ getProfile, saveProfile }));

const MEMBER_A = { id: "member-a", email: "a@example.com", name: "Ada" };
const MEMBER_B = { id: "member-b", email: "b@example.com", name: "Bea" };

beforeEach(() => {
  session.current = { user: MEMBER_A };
  getSession.mockImplementation(async () => session.current);
  getProfile.mockResolvedValue({ about: null });
  saveProfile.mockResolvedValue({ about: null });
});

function Opener() {
  const aboutYou = useAboutYou();
  return (
    <button type="button" onClick={() => aboutYou?.open()}>
      open about you
    </button>
  );
}

// A child whose identity changes with `generation`, standing in for the
// sidebar being replaced (a rotation, a route change).
function Child({ generation }: { generation: number }) {
  return (
    <div key={generation} data-testid={`child-${generation}`}>
      <Opener />
    </div>
  );
}

function tree(generation: number) {
  return (
    <AboutYouProvider>
      {generation % 2 === 0 ? (
        <Child key={`even-${generation}`} generation={generation} />
      ) : (
        <section key={`odd-${generation}`}>
          <Child generation={generation} />
        </section>
      )}
    </AboutYouProvider>
  );
}

async function openDialog() {
  fireEvent.click(screen.getByRole("button", { name: "open about you" }));
  const dialog = await screen.findByRole("dialog", { name: "About you" });
  const textarea = screen.getByRole("textbox", { name: "About you" });
  await vi.waitFor(() => expect(textarea).toBeEnabled());
  return { dialog, textarea };
}

describe("useAboutYou", () => {
  it("is null without a provider", () => {
    const { result } = renderHook(() => useAboutYou());
    expect(result.current).toBeNull();
  });

  it("offers open() inside the provider", () => {
    const { result } = renderHook(() => useAboutYou(), {
      wrapper: ({ children }) => (
        <AboutYouProvider>{children}</AboutYouProvider>
      ),
    });
    expect(result.current).not.toBeNull();
    expect(typeof result.current?.open).toBe("function");
  });
});

describe("AboutYouProvider", () => {
  it("renders no dialog until opened", () => {
    render(tree(0));
    expect(screen.queryByRole("dialog", { name: "About you" })).toBeNull();
  });

  it("renders the About you dialog when opened", async () => {
    render(tree(0));
    const { dialog } = await openDialog();
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("keeps the dialog open with the typed text when its children remount", async () => {
    const { rerender } = render(tree(0));
    const { textarea } = await openDialog();
    fireEvent.change(textarea, { target: { value: "typed before the swap" } });

    rerender(tree(1));
    expect(screen.queryByTestId("child-0")).toBeNull();
    expect(screen.getByTestId("child-1")).toBeInTheDocument();
    rerender(tree(2));

    expect(
      screen.getByRole("dialog", { name: "About you" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "About you" })).toHaveValue(
      "typed before the swap",
    );
    // The dialog was not remounted, so it did not load the note again.
    expect(getProfile).toHaveBeenCalledTimes(1);
  });

  it("closes the dialog when the signed-in member changes", async () => {
    const { rerender } = render(tree(0));
    const { textarea } = await openDialog();
    fireEvent.change(textarea, { target: { value: "member A's typing" } });

    session.current = { user: MEMBER_B };
    rerender(tree(0));

    expect(screen.queryByRole("dialog", { name: "About you" })).toBeNull();
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it("saves when the cookie still belongs to the member the dialog opened for", async () => {
    render(tree(0));
    const { textarea } = await openDialog();
    fireEvent.change(textarea, { target: { value: "member A's note" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await vi.waitFor(() =>
      expect(saveProfile).toHaveBeenCalledWith("member A's note"),
    );
  });

  it("closes without saving when the cookie changed member before useSession caught up", async () => {
    render(tree(0));
    const { textarea } = await openDialog();
    fireEvent.change(textarea, { target: { value: "member A's typing" } });

    // Another tab signed in as B; this tab's useSession still reports A.
    getSession.mockResolvedValue({ user: MEMBER_B });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "About you" })).toBeNull(),
    );
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it("keeps the dialog open when the same member's session re-renders", async () => {
    const { rerender } = render(tree(0));
    await openDialog();

    session.current = { user: { ...MEMBER_A } };
    rerender(tree(0));

    expect(
      screen.getByRole("dialog", { name: "About you" }),
    ).toBeInTheDocument();
  });

  it("closes the dialog on Cancel and can open it again", async () => {
    render(tree(0));
    await openDialog();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "About you" })).toBeNull();

    await act(async () => {});
    await openDialog();
    expect(
      screen.getByRole("dialog", { name: "About you" }),
    ).toBeInTheDocument();
  });
});
