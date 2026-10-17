"""Build a simple GitHub Pages list of weekend Psalm deliveries."""

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "data" / "weekend_psalm_history.json"
OUTPUT_PATH = ROOT / "_site" / "index.html"


def main():
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    items = []
    for entry in reversed(history):
        items.append(
            "<li><time datetime=\"{date}\">{date}</time><p>{message}</p></li>".format(
                date=html.escape(entry["date"], quote=True),
                message=html.escape(entry["message"]).replace("\n", "<br>"),
            )
        )
    entries = "\n".join(items) if items else '<li class="empty">아직 기록된 시편이 없습니다.</li>'
    document = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>금동이네 주말 시편 기록</title>
  <style>
    body { max-width: 720px; margin: 3rem auto; padding: 0 1.25rem; color: #222; font: 1rem/1.7 system-ui, sans-serif; }
    h1 { font-size: 1.75rem; }
    ol { padding: 0; list-style: none; }
    li { padding: 1rem 0; border-bottom: 1px solid #ddd; }
    time { color: #666; font-size: .9rem; }
    p { margin: .35rem 0 0; white-space: normal; }
    .empty { color: #666; }
  </style>
</head>
<body>
  <main>
    <h1>금동이네 주말 시편 기록</h1>
    <ol>
      <!--ENTRIES-->
    </ol>
  </main>
</body>
</html>
""".replace("<!--ENTRIES-->", entries)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
