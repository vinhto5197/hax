"use client";

import { useState, type InputHTMLAttributes } from "react";

import { fieldClass } from "@/components/auth/AuthCard";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "className">;

// A password input with a Show/Hide toggle. Replaces confirm-password fields:
// letting the user see what they typed catches typos without a second entry.
export function PasswordField(props: Props) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <input
        {...props}
        type={visible ? "text" : "password"}
        className={`${fieldClass} pr-16`}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-pressed={visible}
        aria-label={visible ? "Hide password" : "Show password"}
        className="absolute inset-y-0 right-0 px-3 text-xs text-black/60 hover:text-black dark:text-white/60 dark:hover:text-white"
      >
        {visible ? "Hide" : "Show"}
      </button>
    </div>
  );
}
