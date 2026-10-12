import { auth } from "@/auth";
import { NewChatFlow } from "@/components/chat/NewChatFlow";

// The "new chat" landing: no conversation yet. The first message lazily
// creates one server-side and the URL becomes /chat/[id].
export default async function ChatPage() {
  const session = await auth();
  return <NewChatFlow name={session?.user?.name ?? null} />;
}
