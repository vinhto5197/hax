import { ChatWindow } from "@/components/chat/ChatWindow";

// Next 15+ passes route params as a Promise.
export default async function ChatConversationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ChatWindow conversationId={id} />;
}
