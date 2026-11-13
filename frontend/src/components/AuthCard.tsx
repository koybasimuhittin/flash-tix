import { Zap } from "lucide-react";
import type { FormEvent, ReactNode } from "react";

/** Shared frame for the log-in and sign-up forms. */
export function AuthCard({
  title,
  subtitle,
  onSubmit,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  onSubmit: (e: FormEvent) => void;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-sm px-4 py-12 sm:py-20">
      <form className="overflow-hidden rounded-xl border border-border bg-card" onSubmit={onSubmit}>
        <div className="bg-ink px-6 py-6 text-white">
          <Zap className="size-5 fill-stub text-stub" />
          <h1 className="font-poster mt-3 text-4xl">{title}</h1>
          <p className="mt-1 text-sm text-white/70">{subtitle}</p>
        </div>
        <div className="flex flex-col gap-4 p-6">{children}</div>
      </form>
      <p className="mt-4 text-center text-sm text-muted-foreground">{footer}</p>
    </div>
  );
}
