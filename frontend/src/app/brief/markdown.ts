/**
 * A deliberately small Markdown renderer for the brief.
 *
 * Scope: headings, bold, italic, inline code, fenced code, blockquotes, rules,
 * ordered/unordered lists and GFM tables. That is everything the backend's
 * brief template emits and nothing else — pulling in a full Markdown library to
 * render a document we also author would be a dependency with no upside.
 *
 * Safety: the source is escaped in full *before* any tag is introduced, so no
 * substring of the backend's output can close a tag or open an element. The
 * only markup in the result is markup this file wrote. The caller additionally
 * binds through Angular's `[innerHTML]`, which sanitises again.
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Inline spans. Operates on already-escaped text. */
function inline(s: string): string {
  return s
    // `code` first, so emphasis markers inside code are left alone
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>');
}

function isTableDivider(line: string): boolean {
  return /^\s*\|?[\s:-]*-[\s:|-]*\|?\s*$/.test(line) && line.includes('-');
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());
}

export function renderMarkdown(src: string): string {
  if (!src) return '';

  const lines = escapeHtml(src.replace(/\r\n/g, '\n')).split('\n');
  const out: string[] = [];

  let i = 0;
  let para: string[] = [];

  const flushParagraph = (): void => {
    if (para.length) {
      out.push(`<p>${inline(para.join(' '))}</p>`);
      para = [];
    }
  };

  while (i < lines.length) {
    const line = lines[i];

    // blank
    if (!line.trim()) {
      flushParagraph();
      i++;
      continue;
    }

    // fenced code
    if (/^\s*```/.test(line)) {
      flushParagraph();
      i++;
      const buf: string[] = [];
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      i++; // closing fence
      out.push(`<pre><code>${buf.join('\n')}</code></pre>`);
      continue;
    }

    // horizontal rule
    if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) {
      flushParagraph();
      out.push('<hr>');
      i++;
      continue;
    }

    // heading
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      flushParagraph();
      const level = Math.min(h[1].length, 6);
      out.push(`<h${level}>${inline(h[2].trim())}</h${level}>`);
      i++;
      continue;
    }

    // table: a header row followed by a divider row
    if (line.includes('|') && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      flushParagraph();
      const head = splitRow(line);
      i += 2;
      const body: string[][] = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        body.push(splitRow(lines[i]));
        i++;
      }
      const thead = head.map((c) => `<th>${inline(c)}</th>`).join('');
      const tbody = body
        .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`)
        .join('');
      out.push(
        `<div class="table-wrap"><table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table></div>`,
      );
      continue;
    }

    // blockquote
    if (/^\s*&gt;\s?/.test(line)) {
      flushParagraph();
      const buf: string[] = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*&gt;\s?/, ''));
        i++;
      }
      out.push(`<blockquote>${inline(buf.join(' '))}</blockquote>`);
      continue;
    }

    // unordered list
    if (/^\s*[-*+]\s+/.test(line)) {
      flushParagraph();
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*[-*+]\s+/, ''))}</li>`);
        i++;
      }
      out.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    // ordered list
    if (/^\s*\d+[.)]\s+/.test(line)) {
      flushParagraph();
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*\d+[.)]\s+/, ''))}</li>`);
        i++;
      }
      out.push(`<ol>${items.join('')}</ol>`);
      continue;
    }

    // plain prose — accumulated so soft-wrapped lines join into one paragraph
    para.push(line.trim());
    i++;
  }

  flushParagraph();
  return out.join('\n');
}
