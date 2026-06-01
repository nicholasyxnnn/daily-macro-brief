import xml.etree.ElementTree as ET
import re

# XML output schema injected into every synthesis prompt.
# Claude must populate all tags exactly — no additions, no omissions.
OUTPUT_SCHEMA = """
<brief>

  <!-- Module 2: 3 things that matter today. Each item ≤80 words total including so_what. -->
  <module_2>
    <item id="1">
      <headline>One sentence. The insight, not the event.</headline>
      <body>2-3 sentences max. Numbers required.</body>
      <so_what>One sentence referencing a specific position or theme from the book.</so_what>
    </item>
    <item id="2">
      <headline></headline>
      <body></body>
      <so_what></so_what>
    </item>
    <item id="3">
      <headline></headline>
      <body></body>
      <so_what></so_what>
    </item>
  </module_2>

  <!-- Module 4: Select the chart and write a caption ≤30 words. -->
  <module_4>
    <chart_asset>Exact name: USD/JPY | Gold | US 10Y | 2s10s Spread | VIX | DXY | SPY | EM Debt</chart_asset>
    <caption>Chart caption here — ≤30 words, Bloomberg style.</caption>
  </module_4>

  <!-- Module 5: Theme radar. 3 deep-content items from non-mainstream sources only. -->
  <module_5>
    <item id="1">
      <title>Article or piece title</title>
      <source>Source name</source>
      <link>URL</link>
      <summary>60-100 words. Insight-first. No throat-clearing.</summary>
      <book_implication>One sentence: what this means for a specific position in our book.</book_implication>
    </item>
    <item id="2">
      <title></title>
      <source></source>
      <link></link>
      <summary></summary>
      <book_implication></book_implication>
    </item>
    <item id="3">
      <title></title>
      <source></source>
      <link></link>
      <summary></summary>
      <book_implication></book_implication>
    </item>
  </module_5>

  <!-- Module 6: Contrarian corner. 50-100 words on a narrative the market isn't pricing. -->
  <module_6>
    <contrarian_view>50-100 words. Specific, falsifiable claim. Not vibes.</contrarian_view>
  </module_6>

</brief>
"""


def parse_synthesis(xml_text: str) -> dict:
    """Parse Claude's XML output into a structured dict. Returns best-effort on malformed XML."""
    # Strip any text before/after the <brief> block
    match = re.search(r"<brief>.*?</brief>", xml_text, re.DOTALL)
    if not match:
        return {}
    try:
        root = ET.fromstring(match.group(0))
    except ET.ParseError as e:
        print(f"[WARN] XML parse failed ({e}), attempting sanitization...", flush=True)
        sanitized = re.sub(r'&(?!(amp|lt|gt|apos|quot|#\d+);)', '&amp;', match.group(0))
        try:
            root = ET.fromstring(sanitized)
        except ET.ParseError:
            print(f"[ERROR] XML parse failed after sanitization. Raw (first 800 chars):\n{xml_text[:800]}", flush=True)
            return {}

    result = {}

    # Module 2
    m2 = root.find("module_2")
    if m2 is not None:
        items = []
        for item in m2.findall("item"):
            items.append({
                "headline": _text(item, "headline"),
                "body": _text(item, "body"),
                "so_what": _text(item, "so_what"),
            })
        result["module_2"] = items

    # Module 4
    m4 = root.find("module_4")
    if m4 is not None:
        result["module_4_chart_asset"] = _text(m4, "chart_asset")
        result["module_4_caption"] = _text(m4, "caption")

    # Module 5
    m5 = root.find("module_5")
    if m5 is not None:
        items = []
        for item in m5.findall("item"):
            items.append({
                "title": _text(item, "title"),
                "source": _text(item, "source"),
                "link": _text(item, "link"),
                "summary": _text(item, "summary"),
                "book_implication": _text(item, "book_implication"),
            })
        result["module_5"] = items

    # Module 6
    m6 = root.find("module_6")
    if m6 is not None:
        result["module_6"] = _text(m6, "contrarian_view")

    return result


def _text(parent: ET.Element, tag: str) -> str:
    el = parent.find(tag)
    if el is None or el.text is None:
        return ""
    return el.text.strip()
