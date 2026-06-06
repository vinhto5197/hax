import { ChatWindow } from "@/components/chat/ChatWindow";

// The "new chat" landing: no conversation yet. The first message lazily
// creates one server-side and the URL becomes /chat/[id].
export default function ChatPage() {
  return <ChatWindow conversationId={null} />;
}
