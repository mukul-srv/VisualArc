// Counts the controls a person sees at first glance in server-rendered markup: buttons, links, form
// fields and menu summaries that are NOT inside a closed <details> (those are one control, the
// summary). Used by tests that keep screens simple.
const TAGS = /<(button|a|select|input|textarea|summary)\b[^>]*>/g;

/** Remove the bodies of closed <details>, keeping their <summary>. */
function collapse(html: string): string {
  let out = html;
  for (;;) {
    // innermost closed details first (no nested <details> inside the match)
    const next = out.replace(/<details(?![^>]*\bopen\b)[^>]*>((?:(?!<details)[\s\S])*?)<\/details>/, (_m, body: string) => {
      const sum = /<summary\b[^>]*>[\s\S]*?<\/summary>/.exec(body);
      return sum ? sum[0] : "";
    });
    if (next === out) return out;
    out = next;
  }
}

export function visibleControls(html: string): number {
  return [...collapse(html).matchAll(TAGS)].filter((m) => !/type="hidden"/.test(m[0])).length;
}
