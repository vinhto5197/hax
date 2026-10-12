import { ConversationsProvider } from "@/components/chat/ConversationsProvider";
import { Shell } from "@/components/chat/Shell";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Wraps /chat and /chat/[id] with the shell, which holds the conversation
  // sidebar (static or drawer). The provider shares the conversation list (and
  // a refresh trigger) between the sidebar and the chat window.
  return (
    <ConversationsProvider>
      <Shell>{children}</Shell>
    </ConversationsProvider>
  );
}
