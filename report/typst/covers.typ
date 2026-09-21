// ============================================================================
//  封面方案集 —— 仅供挑选，不参与正文排版
//
//  每个方案是一个函数，接收同一个 ctx 字典，内容完全一致、只有版式不同。
//  用法：cover-compare.typ 依次调用，每版一页。
//
//  ⚠️ 各方案必须显式 set par(spacing: 0pt)：默认段距 1.2em 会在十几个块之间
//     累积出几十毫米，足以把内容挤出页面（实测会多出一页只有日期的废页）。
// ============================================================================
#import "template.typ": *

#let ctx-demo = (
  title: "简易拼图游戏的设计与实现",
  doc-type: "初步设计报告",
  eyebrow: "数字电路与逻辑设计实验（下）",
  eyebrow-sub: "综合课题",
  info: (
    ("课程名称", "《数字电路与逻辑设计实验（下）》"),
    ("题目", "题目 4　简易拼图游戏的设计与实现"),
  ),
  date: "2026 年 9 月 20 日",
)

// 居中信息栏：标签右对齐 + 值左对齐
#let info-box(ctx, label-size: 12pt, value-size: 12pt, gutter: 1.4em, row-gutter: 1.3em, tracking: 0.22em) = grid(
  columns: (auto, auto),
  column-gutter: gutter,
  row-gutter: row-gutter,
  align: (right + horizon, left + horizon),
  ..ctx.info
    .map(p => (
      text(font: f-hei, size: label-size, tracking: tracking, p.at(0)),
      text(size: value-size, p.at(1)),
    ))
    .flatten(),
)

// 行内信息栏：标签 + 值同行，整组左对齐
#let info-rows(ctx, label-size: 9.5pt, value-size: 11pt, gutter: 1.5em, row-gutter: 0.5em, tracking: 0.2em) = grid(
  columns: (auto, auto),
  column-gutter: gutter,
  row-gutter: row-gutter,
  align: (right + horizon, left + horizon),
  ..ctx.info
    .map(p => (
      text(font: f-hei, size: label-size, fill: c-sub, tracking: tracking, p.at(0)),
      text(size: value-size, p.at(1)),
    ))
    .flatten(),
)

#let title-2line(size, leading: 0.95em) = block[
  #set par(leading: leading)
  #text(font: f-hei, size: size, weight: "bold")[简易拼图游戏的#linebreak()设计与实现]
]

// ---------------------------------------------------------------------------
// 方案 A · 北邮式居中
// 特征：无装饰；靠居中、双线分隔与字号对比建立层次
// ---------------------------------------------------------------------------
#let cover-a(ctx) = {
  set page(paper: "a4", margin: (x: 2.4cm, y: 2.6cm), header: none, footer: none, numbering: none)
  set par(first-line-indent: 0pt, justify: false, spacing: 0pt)
  align(center)[
    #text(font: f-hei, size: 18pt, tracking: 0.08em)[#ctx.eyebrow]
    #v(0.8em)
    #text(font: f-hei, size: 11pt, fill: c-sub, tracking: 0.35em)[#ctx.eyebrow-sub]
  ]
  v(10mm)
  line(length: 100%, stroke: 1.6pt + c-ink)
  v(0.7mm)
  line(length: 100%, stroke: 0.5pt + c-ink)
  v(13mm)
  align(center)[#text(font: f-hei, size: 14pt, fill: c-sub, tracking: 0.55em)[#ctx.doc-type]]
  v(48mm)
  align(center)[#text(font: f-hei, size: 24pt, weight: "bold", tracking: 0.02em)[#ctx.title]]
  v(58mm)
  align(center)[#info-box(ctx)]
  v(62mm)
  align(center)[#text(font: f-hei, size: 12pt, fill: c-sub, tracking: 0.10em)[#ctx.date]]
}

// ---------------------------------------------------------------------------
// 方案 B · 双线边框式
// 特征：整页双线边框（画在页面背景上），内容居中排列，公文／正式报告常用
// ---------------------------------------------------------------------------
#let cover-b(ctx) = {
  set page(
    paper: "a4",
    margin: (x: 24mm, y: 28mm),
    header: none,
    footer: none,
    numbering: none,
    background: {
      place(top + left, dx: 12mm, dy: 12mm, rect(width: 186mm, height: 273mm, stroke: 1.2pt + c-ink))
      place(top + left, dx: 15mm, dy: 15mm, rect(width: 180mm, height: 267mm, stroke: 0.4pt + c-ink))
    },
  )
  set par(first-line-indent: 0pt, justify: false, spacing: 0pt)
  align(center)[
    #text(font: f-hei, size: 17pt, tracking: 0.10em)[#ctx.eyebrow]
    #v(0.7em)
    #text(font: f-hei, size: 10.5pt, fill: c-sub, tracking: 0.35em)[#ctx.eyebrow-sub]
  ]
  v(20mm)
  align(center)[#text(font: f-hei, size: 14pt, fill: c-sub, tracking: 0.55em)[#ctx.doc-type]]
  v(58mm)
  align(center)[#text(font: f-hei, size: 23pt, weight: "bold")[#ctx.title]]
  v(42mm)
  align(center)[#line(length: 50%, stroke: 0.4pt + c-ink)]
  v(38mm)
  align(center)[#info-box(ctx)]
  v(44mm)
  align(center)[#text(font: f-hei, size: 12pt, fill: c-sub, tracking: 0.10em)[#ctx.date]]
}

// ---------------------------------------------------------------------------
// 方案 C · 左竖栏式
// 特征：左侧一道实心竖栏作版面基准，全部左对齐；内容分上／中／下三段撑满竖栏
// ---------------------------------------------------------------------------
#let cover-c(ctx) = {
  set page(paper: "a4", margin: (x: 22mm, y: 22mm), header: none, footer: none, numbering: none)
  set par(first-line-indent: 0pt, justify: false, spacing: 0pt)
  grid(
    columns: (5mm, 11mm, 1fr),
    align: (left + top, left + top, left + top),
    rect(width: 5mm, height: 214mm, fill: c-ink),
    [],
    block(height: 214mm, width: 100%)[
      #grid(
        rows: (auto, 1fr, auto),
        align: (col, row) => if row == 1 { left + horizon } else { left + top },
        [
          #text(font: f-hei, size: 15pt, tracking: 0.04em)[#ctx.eyebrow]
          #v(0.55em)
          #text(font: f-hei, size: 10.5pt, fill: c-sub, tracking: 0.32em)[#ctx.eyebrow-sub]
          #v(11mm)
          #line(length: 100%, stroke: 0.5pt + c-rule-lite)
        ],
        [
          #text(font: f-hei, size: 12.5pt, fill: c-sub, tracking: 0.45em)[#ctx.doc-type]
          #v(9mm)
          #title-2line(29pt)
          #v(13mm)
          #line(length: 100%, stroke: 1.2pt + c-ink)
        ],
        [
          #info-rows(ctx, label-size: 11.5pt, value-size: 11.5pt)
          #v(11mm)
          #text(font: f-hei, size: 11.5pt, fill: c-sub, tracking: 0.08em)[#ctx.date]
        ],
      )
    ],
  )
}

// ---------------------------------------------------------------------------
// 方案 D · 上下分割式
// 特征：细线把版面分成三段；标识在左上，标题居中段，信息在底段横排两栏
// ---------------------------------------------------------------------------
#let cover-d(ctx) = {
  set page(paper: "a4", margin: (x: 24mm, y: 24mm), header: none, footer: none, numbering: none)
  set par(first-line-indent: 0pt, justify: false, spacing: 0pt)
  block(height: 248mm, width: 100%)[
    #grid(
      rows: (auto, 1fr, auto),
      align: (col, row) => if row == 1 { center + horizon } else { left + top },
      [
        #grid(
          columns: (1fr, auto),
          align: (left + horizon, right + horizon),
          text(font: f-hei, size: 13pt, tracking: 0.06em)[#ctx.eyebrow],
          text(font: f-hei, size: 10.5pt, fill: c-sub, tracking: 0.30em)[#ctx.eyebrow-sub],
        )
        #v(3.5mm)
        #line(length: 100%, stroke: 1.4pt + c-ink)
      ],
      [
        #text(font: f-hei, size: 13pt, fill: c-sub, tracking: 0.55em)[#ctx.doc-type]
        #v(12mm)
        #text(font: f-hei, size: 25pt, weight: "bold")[#ctx.title]
      ],
      [
        #line(length: 100%, stroke: 0.5pt + c-ink)
        #v(8mm)
        #grid(
          columns: (1fr, 1fr),
          align: (left + top, left + top),
          ..ctx.info
            .map(p => block[
              #text(font: f-hei, size: 9.5pt, fill: c-sub, tracking: 0.24em)[#p.at(0)]
              #v(0.5em)
              #text(size: 11pt)[#p.at(1)]
            ])
            .flatten(),
        )
        #v(12mm)
        #align(right)[#text(font: f-hei, size: 11pt, fill: c-sub, tracking: 0.08em)[#ctx.date]]
      ],
    )
  ]
}

// ---------------------------------------------------------------------------
// 方案 E · 极简大字式
// 特征：几乎只有字与留白；题目字号最大，其余信息压到最小
// ---------------------------------------------------------------------------
#let cover-e(ctx) = {
  set page(paper: "a4", margin: (x: 26mm, y: 30mm), header: none, footer: none, numbering: none)
  set par(first-line-indent: 0pt, justify: false, spacing: 0pt)
  block(height: 237mm, width: 100%)[
    #grid(
      rows: (auto, 1fr, auto),
      align: (col, row) => if row == 1 { left + horizon } else { left + bottom },
      [
        #text(font: f-hei, size: 10pt, fill: c-sub, tracking: 0.24em)[#ctx.eyebrow　·　#ctx.eyebrow-sub]
        #v(6mm)
        #line(length: 100%, stroke: 0.4pt + c-rule-lite)
      ],
      [
        #title-2line(36pt, leading: 0.92em)
        #v(12mm)
        #line(length: 100%, stroke: 0.6pt + c-ink)
        #v(6mm)
        #text(font: f-hei, size: 12pt, fill: c-sub, tracking: 0.42em)[#ctx.doc-type]
      ],
      [
        #grid(
          columns: (1fr, auto),
          align: (left + bottom, right + bottom),
          info-rows(ctx),
          text(font: f-hei, size: 10.5pt, fill: c-sub, tracking: 0.06em)[#ctx.date],
        )
      ],
    )
  ]
}
