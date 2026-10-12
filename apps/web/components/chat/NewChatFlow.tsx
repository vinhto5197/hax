"use client";

import { useState } from "react";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { useConversations } from "@/components/chat/ConversationsProvider";
import { NewChat } from "@/components/chat/NewChat";

// A member's new chat: the NewChat screen until the first send, then the
// ChatWindow with that prompt. The name comes from the server page (the
// session read in a server component) so the greeting is right on the first
// render, not after a client session fetch.
export function NewChatFlow({ name }: { name: string | null }) {
  const { newChatNonce } = useConversations();
  return <NewChatFlowSession key={newChatNonce} name={name} />;
}

// Keyed on the nonce above: "+ New chat" from a lazy-created conversation is
// a same-route navigation (the URL came from history.replaceState), so without
// the remount the stored prompt would survive and be sent again into the
// fresh session. The model choice travels with the first prompt.
function NewChatFlowSession({ name }: { name: string | null }) {
  const [prompt, setPrompt] = useState<string | null>(null);
  const [model, setModel] = useState("");
  if (prompt !== null) {
    return (
      <ChatWindow
        conversationId={null}
        initialPrompt={prompt}
        initialModel={model}
      />
    );
  }
  return (
    <NewChat
      name={name}
      chips={[]}
      model={model}
      onModelChange={setModel}
      onSend={async (text) => {
        setPrompt(text);
      }}
    />
  );
}
