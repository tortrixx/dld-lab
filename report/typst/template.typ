// ============================================================================
//  数字电路与逻辑设计实验（下）· 综合课题 · 初步设计方案
//  Typst 版式模板  —— 中文课程设计报告体例
//
//  取用与改进说明：
//    · 封面版式（居中标题区 + 下划线信息栏）参考北邮公开模板
//      simple-bupt-report:0.1.1，并按其版式语言重排为"设计报告"体例：
//      改双线分隔、六项四字信息栏、底部日期，去掉校徽位与学期行
//    · 标题层级按中文课程设计报告通例重定：一级三号黑体居中、
//      二级四号黑体顶格、三级小四黑体左缩进 2 字（缩进这一条取自
//      simple-bupt-report 的三级标题写法）
//    · 三线表与题注体例参考 report-flow-ustc:1.1.0 与 modern-cug-report:0.1.3
//    · 中西文混排的字体回退策略（covers: "latin-in-cjk"）参考 ori:0.2.5
// ============================================================================

// ---------------------------------------------------------------- 字体 ------
// 不用 "SimSun"/"黑体" 这类族名：macOS 上已不带，写错会静默回退成
// 中西文各一套字形。这里用随系统分发的思源系列（Noto CJK），并按用途
// 拆成四种，避免全文一套字体的平板感。
#let f-latin = "IBM Plex Serif"        // 西文正文（衬线）
#let f-cjk = "Noto Serif CJK SC"       // 中文正文（思源宋体）
#let f-hei = "Noto Sans CJK SC"        // 标题、表头、页眉（思源黑体）
#let f-kai = "KaiTi"                   // 强调（楷体）
#let f-mono = "IBM Plex Mono"          // 标识符、端口名

#let f-body = ((name: f-latin, covers: "latin-in-cjk"), f-cjk)
#let f-mono-list = (f-mono, f-hei)

// 正文中的标识符（模块名 / 信号名 / 常量）统一走等宽体，与叙述文字区分。
#let m(s) = text(font: f-mono-list, size: 0.9em, s)

// ---------------------------------------------------------------- 配色 ------
// 中文技术报告以墨色为主，仅封面分隔线保留一处克制的冷调。
#let c-ink = rgb("#111111")
#let c-sub = rgb("#4a4a4a")
#let c-rule = rgb("#1f3a5f")
#let c-rule-lite = rgb("#c9ccd1")
#let c-th-bg = rgb("#f0f1f3")          // 表头底色

// ---------------------------------------------------------------- 计数器 ----
// 图表编号采用"章号-序号"，按章重置。Typst 内建的 figure 计数器在
// 自定义 numbering 与自定义 caption 同时存在时不随章重置（已实测），
// 故自管两只计数器，显式重置、显式读取，编号完全确定。
#let chc = counter(heading)
#let fc = counter("dl-fig")
#let tc = counter("dl-tab")

// ---------------------------------------------------------------- 三线表 ----
// 中文报告通行的三线表：顶线粗、表头下线细、底线粗，无竖线。
#let tbl(
  cols,
  head,
  align-first: center,
  ..cells,
) = {
  set par(first-line-indent: 0pt, justify: false, leading: 0.42em)
  set text(size: 9pt)
  table(
    columns: cols,
    inset: (x: 5pt, y: 4.2pt),
    stroke: none,
    align: (col, _row) => if col == 0 { align-first } else { left + horizon },
    fill: (col, row) => if row == 0 { c-th-bg } else { none },
    table.hline(stroke: 0.9pt + c-ink),
    table.header(..head.map(h => text(font: f-hei, weight: "medium", size: 9pt, h))),
    table.hline(stroke: 0.5pt + c-ink),
    ..cells,
    table.hline(stroke: 0.9pt + c-ink),
  )
}

// 带题注的表格（题注在表上方，居中）
#let tblx(caption, cols, head, align-first: center, ..cells) = {
  tc.step()
  context {
    let ch = chc.get().at(0, default: 0)
    let n = tc.get().first()
    let pre = "表 " + numbering("1-1", ch, n) + "　"
    figure(
      kind: table,
      numbering: none,
      supplement: none,
      caption: [#pre#caption],
      tbl(cols, head, align-first: align-first, ..cells.pos()),
    )
  }
}

// ---------------------------------------------------------------- 插图 ------
#let figx(caption, body, width: 100%) = {
  fc.step()
  context {
    let ch = chc.get().at(0, default: 0)
    let n = fc.get().first()
    let pre = "图 " + numbering("1-1", ch, n) + "　"
    figure(
      numbering: none,
      supplement: none,
      caption: [#pre#caption],
      align(center, box(width: width, body)),
    )
  }
}

// ---------------------------------------------------------------- 主模板 ----
#let report(
  title: "标题",
  subtitle: none,
  eyebrow: none,
  eyebrow-sub: none,
  running-title: none,
  running-head: true,
  info: (),
  date: none,
  abstract: none,
  toc: true,
  doc,
) = {
  let running-title = if running-title == none { title } else { running-title }
  // ---- 全局文本与段落 ----
  set text(font: f-body, size: 10.5pt, fill: c-ink, lang: "zh", region: "cn")
  set par(
    justify: true,
    leading: 0.62em,
    spacing: 0.28em,
    first-line-indent: (amount: 2em, all: true),
  )
  show smartquote: set text(font: f-latin)
  show emph: set text(font: ((name: f-kai, covers: "latin-in-cjk"), f-kai), style: "normal")
  show strong: set text(weight: "bold")
  show raw: set text(font: f-mono-list)
  // 行内代码：仅换字体、不加底色，避免正文被色块切碎
  show raw.where(block: false): it => box(baseline: 0.06em, it)

  // ---- 标题层级 ----
  // 中文课程设计报告通例：一级三号黑体居中、二级四号黑体顶格、
  // 三级小四黑体左缩进 2 字，正文五号宋体。层级靠字号 + 对齐 + 缩进三重区分。
  set heading(numbering: (..n) => {
    let p = n.pos()
    numbering(range(p.len()).map(_ => "1").join("."), ..p)
  })

  // ---- 标题层级 ----
  // 中文课程设计报告通例：一级三号黑体居中、二级四号黑体顶格、
  // 三级小四黑体左缩进 2 字，正文五号宋体。层级靠字号 + 对齐 + 缩进三重区分。
  // 段前后的留白按层级递增：上级标题与上下文之间始终比下级更松，
  // 读者不看字号也能从上下的空白判断这一层是"章"还是"节"。
  set heading(numbering: (..n) => {
    let p = n.pos()
    numbering(range(p.len()).map(_ => "1").join("."), ..p)
  })

  show heading: it => {
    set par(first-line-indent: 0pt, justify: false, leading: 0.85em)
    let lvl = it.level
    if lvl == 1 { fc.update(0); tc.update(0) }
    let spec = if lvl == 1 { (16pt, 2.05em, 1.15em) }
      else if lvl == 2 { (14pt, 1.58em, 0.80em) }
      else { (12pt, 1.25em, 0.58em) }
    let (sz, above, below) = spec
    let txt = if it.numbering == none {
      text(font: f-hei, size: sz, weight: "bold")[#it.body]
    } else {
      context {
        let num = numbering(it.numbering, ..counter(heading).at(it.location()))
        text(font: f-hei, size: sz, weight: "bold")[#num　#it.body]
      }
    }
    if lvl == 1 {
      block(above: above, below: below, width: 100%, align(center, txt))
    } else if lvl == 2 {
      block(above: above, below: below, width: 100%, txt)
    } else {
      block(above: above, below: below, width: 100%, inset: (left: 2em), txt)
    }
  }

  // ---- 图/表题注 ----
  // 中文惯例：题注居中，小五号；表题在上、图题在下，编号与题名之间用全角空格。
  // 题注自身的上下留白只留"题注↔图表本体"那一段；与正文之间的距离
  // 统一交给下面 figure 块的 above/below，避免两处叠加后失控。
  show figure.caption: it => {
    set par(first-line-indent: 0pt, justify: false, leading: 0.5em)
    set text(size: 9pt, font: f-body, fill: c-ink)
    let (a, b) = if it.position == top { (0pt, 0.62em) } else { (0.72em, 0pt) }
    block(above: a, below: b, align(center, it.body))
  }
  show figure.where(kind: table): set figure.caption(position: top)
  // 图表与正文之间的留白：上方略大于下方，使图表"贴住"它所属的段落。
  show figure.where(kind: table): set block(above: 1.75em, below: 1.30em)
  show figure.where(kind: image): set block(above: 1.45em, below: 1.45em)
  // 插图与题注视为整体，不拆页。
  show figure.where(kind: image): set block(breakable: false)
  // ⚠️ figure 默认**不可断页**：内含的表格放不下时会整张挪到下一页，
  // 把上一页底部留成大片空白（实测：剩余 9.7cm、表高 10.3cm 时不拆，整表后移）。
  // 必须显式打开，表格才会在行间断开、表头自动重复。
  // 注意 set block(breakable: true) 有效，而 show figure: it => block(...) 包裹无效。
  show figure.where(kind: table): set block(breakable: true)

  // ---- 列表（全文使用极少，仅用于确实并列、无先后关系的要点）----
  set list(indent: 1.6em, marker: text(font: f-hei, fill: c-sub)[·])
  set enum(indent: 1.6em)
  show list.item: it => { set par(first-line-indent: 0pt); it }

  // =========================== 封面 ===========================
  // 体例参照北邮本科毕业设计（论文）封面：居中、对称、不使用装饰性图形，
  // 自上而下为「课程 / 课题标识 → 双线 → 文档类型 → 题目 → 信息栏 → 日期」。
  // 页边距按北邮模板的 155mm×245mm 版心折算，取上下 2.6cm、左右 2.4cm。
  set page(
    paper: "a4",
    margin: (x: 2.4cm, y: 2.6cm),
    header: none,
    footer: none,
    numbering: none,
  )
  set par(first-line-indent: 0pt, justify: false)

  // ---- 顶部标识 ----
  align(center)[
    #text(font: f-hei, size: 18pt, tracking: 0.08em)[#eyebrow]
    #v(0.8em)
    #text(font: f-hei, size: 11pt, fill: c-sub, tracking: 0.35em)[#eyebrow-sub]
  ]

  v(10mm)
  line(length: 100%, stroke: 1.6pt + c-ink)
  v(0.7mm)
  line(length: 100%, stroke: 0.5pt + c-ink)

  // ---- 文档类型 ----
  v(13mm)
  align(center)[
    #text(font: f-hei, size: 14pt, fill: c-sub, tracking: 0.55em)[初步设计报告]
  ]

  // ---- 题目 ----
  v(48mm)
  align(center)[
    #text(font: f-hei, size: 24pt, weight: "bold", tracking: 0.02em)[#title]
  ]

  // ---- 信息栏 ----
  v(58mm)
  align(center)[
    #grid(
      columns: (auto, auto),
      column-gutter: 1.4em,
      row-gutter: 1.3em,
      align: (right + horizon, left + horizon),
      ..info
        .map(pair => (
          text(font: f-hei, size: 12pt, tracking: 0.22em, pair.at(0)),
          text(size: 12pt, pair.at(1)),
        ))
        .flatten(),
    )
  ]

  // ---- 日期 ----
  v(62mm)
  if date != none [
    #align(center)[
      #text(font: f-hei, size: 12pt, fill: c-sub, tracking: 0.10em)[#date]
    ]
  ]

  pagebreak()

  // =========================== 目录 ===========================
  if toc {
    set page(
      paper: "a4",
      margin: (x: 2.3cm, y: 2.2cm),
      numbering: none,
      header: none,
      footer: none,
    )
    show outline.entry: it => {
      set par(first-line-indent: 0pt, justify: false, leading: 0.6em)
      it
    }
    set outline.entry(fill: repeat(text(fill: rgb("#a8abb0"))[·], gap: 0.3em))
    context outline(
      title: align(center, text(font: f-hei, size: 16pt, weight: "bold")[目　录]),
      depth: 2,
      indent: 1.5em,
    )
    pagebreak()
  }

  // =========================== 正文 ===========================
  counter(page).update(1)
  set page(
    paper: "a4",
    margin: (x: 2.3cm, y: 2.2cm),
    numbering: "1",
    header: if running-head {
      context {
        set text(font: f-hei, size: 8pt, fill: rgb("#6a6f77"))
        set par(first-line-indent: 0pt, justify: false)
        align(center)[#running-title]
        v(0.34em)
        line(length: 100%, stroke: 0.5pt + c-rule-lite)
      }
    } else {
      none
    },
    footer: context {
      set text(font: f-hei, size: 9pt, fill: rgb("#4a4a4a"))
      set par(first-line-indent: 0pt, justify: false)
      align(center)[#counter(page).display("1")]
    },
  )

  // 执行摘要（不编号，独立成节）
  if abstract != none {
    heading(level: 1, numbering: none, outlined: true)[执行摘要]
    abstract
  }

  doc
}
