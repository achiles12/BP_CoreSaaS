"use client";
// List search box: local text, written to the URL after 300 ms (D3, F8).
import { Search } from "lucide-react";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";

const DEBOUNCE_MS = 300;

export function SearchInput({
  value,
  onChange,
  placeholder,
  label = "Search",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  label?: string;
}) {
  const [text, setText] = useState(value);
  // URL changed elsewhere (back button, reset): follow it. Adjusting state
  // during render (not in an effect) avoids a second render pass.
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    setText(value);
  }
  useEffect(() => {
    if (text.trim() === value) return;
    const t = setTimeout(() => onChange(text.trim()), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [text, value, onChange]);
  return (
    <div className="relative min-w-48 flex-1">
      <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" aria-hidden />
      <Input
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        aria-label={label}
        className="pl-8"
        maxLength={100}
      />
    </div>
  );
}
