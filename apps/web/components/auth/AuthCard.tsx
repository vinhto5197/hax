export function AuthCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4 rounded-lg border border-black/10 p-6 dark:border-white/10">
        <h1 className="text-xl font-bold">{title}</h1>
        {children}
      </div>
    </div>
  );
}

export const fieldClass =
  "w-full rounded-md border border-black/20 bg-transparent px-3 py-2 text-sm dark:border-white/20";
export const buttonClass =
  "w-full rounded-md bg-foreground px-3 py-2 text-sm text-background disabled:opacity-50";
