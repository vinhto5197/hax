import { AboutYouProvider } from "@/components/chat/AboutYouProvider";
import { ConversationsProvider } from "@/components/chat/ConversationsProvider";
import { Shell } from "@/components/chat/Shell";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Wraps /chat and /chat/[id] with the shell, which holds the conversation
  // sidebar (static or drawer). The provider shares the conversation list (and
  // a refresh trigger) between the sidebar and the chat window. The About you
  // dialog lives here too, outside the sidebar, so a route change or a swapped
  // sidebar keeps it and its text.
  return (
    <ConversationsProvider>
      <AboutYouProvider>
        <Shell>{children}</Shell>
      </AboutYouProvider>
    </ConversationsProvider>
  );
}
