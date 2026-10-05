import Link from "next/link";

export const metadata = { title: "Privacy — hax" };

// Public (middleware). Plain statements of what the service stores and who
// processes it; keep it true when a provider or a data flow changes.
export default function Privacy() {
  return (
    <main className="mx-auto max-w-2xl space-y-6 p-6 text-sm leading-relaxed">
      <h1 className="text-2xl font-bold">Privacy</h1>
      <p>
        hax is an open-source chat assistant that answers questions from the
        documents you upload. This page says what it stores and who else touches
        that data.
      </p>

      <h2 className="text-lg font-semibold">What is stored</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          Your account: email address, a hash of your password (never the
          password), or the identity Google reports if you sign in with Google.
        </li>
        <li>Your conversations: the messages you send and the replies.</li>
        <li>
          Your uploads: the files themselves, and the text and numeric
          embeddings derived from them for search.
        </li>
        <li>
          A session cookie so you stay signed in. There are no advertising or
          analytics cookies.
        </li>
        <li>
          If you try hax without an account, a guest session cookie and the few
          messages of that demo, which are deleted after a few days.
        </li>
        <li>
          Your network address, for up to a day, in counters that limit sign-up
          and demo attempts, and in request logs that rotate within days.
        </li>
      </ul>

      <h2 className="text-lg font-semibold">Who processes it</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          Amazon Web Services (US East) hosts the database and file storage.
        </li>
        <li>
          Anthropic receives your messages and relevant excerpts of your
          documents to generate replies.
        </li>
        <li>
          Voyage AI receives document text, and the search queries derived from
          your messages, to compute embeddings.
        </li>
        <li>Resend delivers verification and password-reset emails.</li>
        <li>
          Google provides sign-in if you choose it; hax receives only your email
          address, name and profile picture.
        </li>
      </ul>
      <p>Nothing is sold, and nothing is used for advertising.</p>

      <h2 className="text-lg font-semibold">Isolation and deletion</h2>
      <p>
        Each user&apos;s conversations and documents are visible only to that
        user, enforced in the database. Deleting a conversation or a document in
        the app removes it and everything derived from it right away; database
        backups holding a copy expire on their own within days. To delete your
        account and all its data, email the address below.
      </p>

      <h2 className="text-lg font-semibold">Contact</h2>
      <p>
        <a className="underline" href="mailto:vinhto5197@gmail.com">
          vinhto5197@gmail.com
        </a>
      </p>
      <p>
        <Link className="underline" href="/login">
          Back to sign in
        </Link>
      </p>
    </main>
  );
}
