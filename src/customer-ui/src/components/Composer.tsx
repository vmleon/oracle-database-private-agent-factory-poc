import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";

export function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (disabled || !text.trim()) return;
    onSend(text);
    setText("");
  };

  return (
    <form
      onSubmit={submit}
      className="flex gap-2 border-t border-paper-hair px-5 py-4"
    >
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={disabled}
        placeholder={disabled ? "Waiting for a reply" : "Write a message"}
        className="flex-1 rounded-card border border-paper-hair bg-paper-raised px-4 py-2.5 text-sm text-ink placeholder:text-graphite/70 focus:border-graphite disabled:opacity-60"
      />
      <Button type="submit" disabled={disabled || !text.trim()}>
        Send
      </Button>
    </form>
  );
}
