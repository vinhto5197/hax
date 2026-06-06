import { ConversationsProvider } from "@/components/chat/ConversationsProvider";
import { Sidebar } from "@/components/chat/Sidebar";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Wraps /chat and /chat/[id] with the conversation sidebar. The provider
  // shares the conversation list (and a refresh trigger) between the sidebar
  // and the chat window.
  return (
    <ConversationsProvider>
      <div className="flex h-screen">
        <Sidebar />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </ConversationsProvider>
  );
}
