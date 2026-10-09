/* Voice TTS - pure text helpers: what a file or a paste turns into before it
   is read. No DOM here, so `node test_web.js` checks it as the page runs it. */

'use strict';

(function (root) {
  // Markdown is written to be looked at; read aloud, its syntax is noise. Keep
  // the words and drop the marks: code blocks go entirely (nobody wants C read
  // to them), link text stays and its URL goes, table cells become a list.
  function stripMarkdown(src) {
    const lines = src.replace(/\r\n?/g, '\n').split('\n');
    const out = [];
    let fence = null;   // the ``` or ~~~ that opened the block being skipped

    for (let line of lines) {
      const opener = line.match(/^\s{0,3}(`{3,}|~{3,})/);
      if (fence) {
        if (opener && opener[1][0] === fence[0] && opener[1].length >= fence.length) fence = null;
        continue;
      }
      if (opener) { fence = opener[1]; continue; }

      if (/^\s{0,3}\[[^\]]+\]:\s*\S/.test(line)) continue;          // [ref]: url
      if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) continue;      // --- *** ___
      if (/^\s{0,3}=+\s*$/.test(line)) continue;                      // setext ===
      if (/^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line)) continue;  // |---|

      line = line.replace(/^\s{0,3}#{1,6}\s+(.*?)(\s+#+)?\s*$/, '$1');  // # heading #
      line = line.replace(/^(\s*>\s?)+/, '');                          // > quote
      line = line.replace(/^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?/, '');  // - [x] item
      if (/^\s*\|.*\|\s*$/.test(line)) {                               // | a | b |
        line = line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim()).join(', ');
      }
      out.push(line);
    }

    let text = out.join('\n');
    // Escaped marks are kept as the characters they protect; park them first so
    // the emphasis rules below never see them.
    const escaped = [];
    text = text.replace(/\\([\\`*_{}[\]()#+\-.!~|<>])/g, (_, c) => {
      escaped.push(c);
      return `\u0000${escaped.length - 1}\u0000`;
    });
    text = text
      .replace(/!\[[^\]]*\]\([^)]*\)/g, '')                     // images
      .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')                  // [text](url)
      .replace(/\[([^\]]+)\]\[[^\]]*\]/g, '$1')                 // [text][ref]
      .replace(/<(?:https?|mailto|ftp):[^>\s]*>/gi, '')         // <https://...>
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<(?!\/?en>)\/?[a-z][^>]*>/gi, '')               // HTML, but not <en>
      .replace(/`([^`]+)`/g, '$1')                              // `code`
      .replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, '$2')           // **bold** __bold__
      .replace(/(^|[^\w*])\*(?=\S)([^*\n]*?\S)\*(?![\w*])/g, '$1$2')   // *italic*
      .replace(/(^|[^\w])_(?=\S)([^_\n]*?\S)_(?!\w)/g, '$1$2')         // _italic_
      .replace(/~~(?=\S)([\s\S]*?\S)~~/g, '$1');                // ~~strike~~
    text = text.replace(/\u0000(\d+)\u0000/g, (_, i) => escaped[Number(i)]);

    return text
      .split('\n').map((l) => l.replace(/[ \t]+/g, ' ').replace(/ +$/, '')).join('\n')
      .replace(/ +([.,;:!?])/g, '$1')    // "Ảnh  ở đây" left by a dropped image
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  // A dropped or picked file, as text to read. UTF-8, with or without a BOM;
  // Markdown is recognised by its extension only, so a .txt stays as written.
  function decodeFile(bytes, name) {
    const text = new TextDecoder('utf-8').decode(bytes).replace(/\r\n?/g, '\n');
    return /\.(md|markdown)$/i.test(name) ? stripMarkdown(text) : text;
  }

  const api = { stripMarkdown, decodeFile };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.VoiceText = api;
})(this);
