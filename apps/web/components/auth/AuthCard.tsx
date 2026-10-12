import { PublicHeader } from "@/components/PublicHeader";

export function AuthCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <PublicHeader />
      <div className="flex flex-1 items-center justify-center p-4">
        <div className="w-full max-w-sm space-y-4 rounded-card border border-border bg-surface-1 p-6">
          <h1 className="text-title font-semibold">{title}</h1>
          {children}
        </div>
      </div>
    </div>
  );
}

export const fieldClass =
  "w-full rounded-control border border-border-control bg-surface-1 px-3 py-2 text-body text-ink";
export const buttonClass =
  "w-full rounded-control bg-accent px-3 py-2 text-body font-medium text-accent-ink disabled:opacity-50";
