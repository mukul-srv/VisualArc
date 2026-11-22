"use client";

import { useState } from "react";

/** One visible line of help for a group of controls: it shows what the hovered or keyboard-focused
 *  control does, so touch and keyboard users read the same text a mouse user gets as a tooltip. */
export function useHelp() {
  const [help, setHelp] = useState("");
  const about = (text: string) => ({
    title: text,
    onFocus: () => setHelp(text),
    onBlur: () => setHelp(""),
    onMouseEnter: () => setHelp(text),
    onMouseLeave: () => setHelp(""),
  });
  return { help, about };
}

export function HelpLine({ text }: { text: string }) {
  return <small role="note" style={{ display: "block", minHeight: "1.2em" }}>{text}</small>;
}
