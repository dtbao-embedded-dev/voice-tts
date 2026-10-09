// Fast checks for the page's pure text helpers (web/text.js), under node:
//
//     node test_web.js
//
// No browser and no backend: what is tested here is what decides which words
// reach the engine, so it is checked byte for byte.

'use strict';

const assert = require('node:assert/strict');
const text = require('./web/text.js');

function checkStripMarkdown() {
  const { stripMarkdown } = text;
  const cases = [
    ['# Tiêu đề\n\nĐoạn văn.', 'Tiêu đề\n\nĐoạn văn.'],
    ['## Mục 2 ##', 'Mục 2'],
    ['Tiêu đề\n=======\n\nThân bài', 'Tiêu đề\n\nThân bài'],
    ['Một **đậm** và *nghiêng*, __đậm__ và _nghiêng_, ~~gạch~~.',
      'Một đậm và nghiêng, đậm và nghiêng, gạch.'],
    // snake_case and a lone asterisk are words, not emphasis.
    ['Gọi read_config_file với 2 * 3', 'Gọi read_config_file với 2 * 3'],
    ['Xem [tài liệu](https://example.com/docs "tựa") và [ref][1].\n\n[1]: https://x.y',
      'Xem tài liệu và ref.'],
    ['Ảnh ![sơ đồ khối](img/block.png) ở đây.', 'Ảnh ở đây.'],
    ['Link <https://example.com> tự động.', 'Link tự động.'],
    ['- một\n* hai\n+ ba\n1. bốn\n2) năm\n- [ ] việc\n- [x] xong',
      'một\nhai\nba\nbốn\nnăm\nviệc\nxong'],
    ['> Trích dẫn\n> > lồng nhau', 'Trích dẫn\nlồng nhau'],
    ['| Chân | Chức năng |\n|---|:---:|\n| GPIO0 | Boot |\n| EN | Reset |',
      'Chân, Chức năng\nGPIO0, Boot\nEN, Reset'],
    ['Trước\n\n```c\nint main(void) { return 0; }\n```\n\nSau', 'Trước\n\nSau'],
    ['Trước\n~~~\ncode\n~~~\nSau', 'Trước\nSau'],
    ['Gọi `esp_restart()` để khởi động lại.', 'Gọi esp_restart() để khởi động lại.'],
    ['Phần một\n\n---\n\nPhần hai\n\n***', 'Phần một\n\nPhần hai'],
    ['Dòng<br>mới và <b>đậm</b>, giữ <en>board</en>.', 'Dòng\nmới và đậm, giữ <en>board</en>.'],
    ['Giá \\*không\\* nghiêng', 'Giá *không* nghiêng'],
    ['a\n\n\n\n\nb   ', 'a\n\nb'],
  ];
  for (const [src, want] of cases) {
    assert.equal(stripMarkdown(src), want, JSON.stringify(src));
  }
  console.log('markdown: headings, emphasis, links, images, lists, quotes, tables, code');
}

function checkDecode() {
  const { decodeFile } = text;
  const bytes = (s) => new TextEncoder().encode(s);
  const bom = new Uint8Array([0xef, 0xbb, 0xbf, ...bytes('Xin chào')]);
  assert.equal(decodeFile(bom, 'a.txt'), 'Xin chào', 'BOM kept');
  assert.equal(decodeFile(bytes('# Đầu\r\nthân'), 'GHI-CHU.MD'), 'Đầu\nthân', '.md not stripped');
  assert.equal(decodeFile(bytes('# giữ nguyên\r\n'), 'a.txt'), '# giữ nguyên\n', '.txt changed');
  assert.equal(decodeFile(bytes('*x*'), 'a.markdown'), 'x', '.markdown not stripped');
  console.log('decode: UTF-8 with or without BOM, CRLF, Markdown by extension only');
}

checkStripMarkdown();
checkDecode();
console.log('OK');
