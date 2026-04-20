from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

from content_ops import CONFIG_DIR, DATA_DIR, DOCS_DIR, load_json


def build_site() -> None:
    brand = load_json(CONFIG_DIR / "brand.json", {})
    posts = load_json(DATA_DIR / "posts.json", [])

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "blog").mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "assets" / "covers").mkdir(parents=True, exist_ok=True)

    for post in posts:
        if not post.get("cover_image"):
            render_cover_svg(post)
        render_post_page(brand, post)

    render_home_page(brand, posts)
    render_blog_index(brand, posts)
    render_robots_txt(brand)
    render_sitemap(brand, posts)


def render_home_page(brand: dict, posts: list[dict]) -> None:
    latest_cards = render_post_cards(posts[:6], page="home")
    hero_link = "./blog/" if not posts else f"./blog/{posts[0]['slug']}.html"
    body = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(brand.get("site_name", "Blog"))}</title>
  <meta name="description" content="{escape(brand.get("homepage_intro", ""))}">
  <link rel="stylesheet" href="./assets/site.css">
</head>
<body>
  {header(brand, ".")}
  <main class="shell">
    <section class="hero hero-home">
      <div class="hero-copy">
        <span class="eyebrow">Contenido orgánico automatizado</span>
        <h1>{escape(brand.get("site_name", "Blog"))}</h1>
        <p>{escape(brand.get("homepage_intro", ""))}</p>
        <div class="cta-row">
          <a class="button button-primary" href="{hero_link}">Leer la pieza destacada</a>
          <a class="button button-secondary" href="./blog/">Ver el archivo completo</a>
        </div>
      </div>
      <div class="hero-note panel">
        <span class="eyebrow">Línea editorial</span>
        <h2>No publicamos por publicar.</h2>
        <p>Tomamos noticias, investigación y buenas prácticas. Luego las convertimos en una lectura ejecutiva, provocadora y útil para empresas que quieren mover operaciones, no solo experimentar.</p>
      </div>
    </section>
    <section class="section-head">
      <span class="eyebrow">Últimos análisis</span>
      <h2>Ideas con criterio. Ritmo. Y una tesis clara.</h2>
      <p class="lede">{escape(brand.get("site_tagline", ""))}</p>
    </section>
    {latest_cards}
  </main>
  {footer(brand)}
</body>
</html>
"""
    write(DOCS_DIR / "index.html", body)


def render_blog_index(brand: dict, posts: list[dict]) -> None:
    cards = render_post_cards(posts, page="blog")
    body = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Blog | {escape(brand.get("site_name", "Blog"))}</title>
  <meta name="description" content="{escape(brand.get("site_tagline", ""))}">
  <link rel="stylesheet" href="../assets/site.css">
</head>
<body>
  {header(brand, "..")}
  <main class="shell">
    <section class="hero hero-blog">
      <div class="hero-copy">
        <span class="eyebrow">Blog</span>
        <h1>Contenido que abre conversaciones comerciales de verdad.</h1>
        <p>{escape(brand.get("homepage_intro", ""))}</p>
      </div>
    </section>
    {cards}
  </main>
  {footer(brand)}
</body>
</html>
"""
    write(DOCS_DIR / "blog" / "index.html", body)


def render_post_page(brand: dict, post: dict) -> None:
    title = escape(post["title"])
    description = escape(post.get("excerpt", ""))
    source_links = "".join(
        f'<li><a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(url)}</a></li>'
        for url in post.get("source_urls", [])
    )
    source_links = source_links or "<li>Fuente principal no disponible.</li>"
    deck = escape(post.get("deck") or post.get("excerpt", ""))
    pull_quote = escape(post.get("pull_quote") or "")
    cover_image = resolve_cover_image(post, page="post")
    takeaways = render_takeaways(post.get("key_takeaways", []))
    cta_title = escape(post.get("cta_title") or "Convirtamos esta idea en una ventaja operativa.")
    cta_body = escape(
        post.get("cta_body")
        or "Si quieres aterrizar esta tendencia en un caso de uso real, te ayudamos a convertirla en un piloto con alcance, métricas y criterio."
    )

    body = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | {escape(brand.get("site_name", "Blog"))}</title>
  <meta name="description" content="{description}">
  <link rel="stylesheet" href="../assets/site.css">
  <link rel="canonical" href="{escape(post.get("canonical_url", ""))}">
</head>
<body>
  {header(brand, "..")}
  <main class="shell">
    <article class="story">
      <section class="story-hero">
        <div class="story-copy">
          <span class="eyebrow">{escape(post.get("cover_label") or post.get("source_name", "Análisis"))}</span>
          <h1>{title}</h1>
          <p class="deck">{deck}</p>
          <div class="meta meta-hero">
            <span>{format_date(post.get("published_at"))}</span>
            <span>{escape(post.get("source_name", "Curación automatizada"))}</span>
            <span>{reading_time(post)} min de lectura</span>
            <span>{escape(post.get("editorial_role", {}).get("label", "Editorial"))}</span>
          </div>
        </div>
        <div class="story-cover panel">
          <img src="{cover_image['src']}" alt="{escape(cover_image['alt'])}">
          {render_image_credit(post)}
        </div>
      </section>
      {takeaways}
      {render_quote_block(pull_quote)}
      <section class="article-shell">
        <div class="article-body">
          {post.get("article_html", "")}
        </div>
      </section>
      <section class="cta-panel panel">
        <span class="eyebrow">Siguiente paso</span>
        <h2>{cta_title}</h2>
        <p>{cta_body}</p>
      </section>
      <section class="sources panel">
        <h2>Fuentes y referencias</h2>
        <ul>{source_links}</ul>
      </section>
    </article>
  </main>
  {footer(brand)}
</body>
</html>
"""
    write(DOCS_DIR / "blog" / f"{post['slug']}.html", body)


def render_post_cards(posts: list[dict], page: str) -> str:
    if not posts:
        return '<div class="empty">Aún no hay artículos publicados. El primer run del pipeline creará la primera pieza.</div>'

    cards: list[str] = []
    for post in posts:
        href = link_for_card(post, page)
        cover_image = resolve_cover_image(post, page=page)
        cards.append(
            f"""
<article class="post-card">
  <a class="card-cover" href="{href}">
    <img src="{cover_image['src']}" alt="{escape(cover_image['alt'])}">
  </a>
  <div class="post-card-body">
    <div class="meta">
      <span>{format_date(post.get("published_at"))}</span>
      <span>{escape(post.get("source_name", "Curación automatizada"))}</span>
    </div>
    <h3><a href="{href}">{escape(post["title"])}</a></h3>
    <p class="card-deck">{escape(post.get("deck") or post.get("excerpt", ""))}</p>
    <p>{escape(post.get("excerpt", ""))}</p>
    <a class="button button-secondary" href="{href}">Leer articulo</a>
  </div>
</article>
""".strip()
        )
    return f'<section class="post-grid">{"".join(cards)}</section>'


def render_takeaways(items: list[str]) -> str:
    if not items:
        return ""
    rows = "".join(f"<li>{escape(item)}</li>" for item in items[:3] if item)
    if not rows:
        return ""
    return f"""
<section class="takeaways panel">
  <span class="eyebrow">En 30 segundos</span>
  <h2>Lo que importa de verdad</h2>
  <ul>{rows}</ul>
</section>
""".strip()


def render_quote_block(value: str) -> str:
    if not value:
        return ""
    return f"""
<section class="quote-band">
  <blockquote>{value}</blockquote>
</section>
""".strip()


def render_image_credit(post: dict) -> str:
    cover_image = post.get("cover_image")
    if not cover_image:
        return ""
    photographer = escape(cover_image.get("photographer") or "")
    photographer_url = cover_image.get("photographer_url") or ""
    source_url = cover_image.get("source_url") or ""
    label = escape(cover_image.get("attribution_label") or "Imagen editorial")
    parts = [label]
    if photographer and photographer_url:
        parts.append(f'<a href="{escape(photographer_url)}" target="_blank" rel="noopener noreferrer">{photographer}</a>')
    elif photographer:
        parts.append(photographer)
    if source_url:
        parts.append(f'<a href="{escape(source_url)}" target="_blank" rel="noopener noreferrer">ver fuente</a>')
    return f'<p class="image-credit">{" · ".join(parts)}</p>'


def render_robots_txt(brand: dict) -> None:
    base_url = brand.get("base_url", "").rstrip("/")
    content = f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n"
    write(DOCS_DIR / "robots.txt", content)


def render_sitemap(brand: dict, posts: list[dict]) -> None:
    base_url = brand.get("base_url", "").rstrip("/")
    urls = [f"{base_url}/", f"{base_url}/blog/"]
    urls.extend(post.get("canonical_url", "") for post in posts if post.get("canonical_url"))
    rows = "\n".join(f"  <url><loc>{escape(url)}</loc></url>" for url in urls)
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{rows}
</urlset>
"""
    write(DOCS_DIR / "sitemap.xml", content)


def render_cover_svg(post: dict) -> None:
    title = post.get("title", "Artículo")
    theme = theme_palette(post.get("cover_theme") or post.get("source_name", "signal"))
    lines = wrap_text(title, width=24, max_lines=4)
    title_svg = "".join(
        f'<text x="54" y="{168 + index * 56}" class="title">{escape(line)}</text>'
        for index, line in enumerate(lines)
    )
    eyebrow = escape(post.get("cover_label") or post.get("source_name", "Análisis"))
    excerpt = escape((post.get("excerpt") or "")[:140])
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675" role="img" aria-label="{escape(title)}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{theme['start']}"/>
      <stop offset="100%" stop-color="{theme['end']}"/>
    </linearGradient>
  </defs>
  <style>
    .eyebrow {{ font: 700 24px Georgia, serif; letter-spacing: 0.18em; text-transform: uppercase; fill: rgba(255,255,255,0.82); }}
    .title {{ font: 700 54px Georgia, serif; fill: white; }}
    .excerpt {{ font: 400 25px Georgia, serif; fill: rgba(255,255,255,0.84); }}
    .badge {{ font: 700 18px Georgia, serif; fill: {theme['ink']}; }}
  </style>
  <rect width="1200" height="675" rx="38" fill="url(#bg)"/>
  <circle cx="1040" cy="122" r="140" fill="rgba(255,255,255,0.08)"/>
  <circle cx="1125" cy="220" r="72" fill="rgba(255,255,255,0.12)"/>
  <rect x="54" y="66" width="336" height="44" rx="22" fill="rgba(255,255,255,0.16)"/>
  <text x="78" y="95" class="eyebrow">{eyebrow}</text>
  {title_svg}
  <text x="54" y="520" class="excerpt">{excerpt}</text>
  <rect x="54" y="570" width="228" height="50" rx="25" fill="{theme['paper']}"/>
  <text x="86" y="602" class="badge">Contenido editorial</text>
</svg>
"""
    write(DOCS_DIR / "assets" / "covers" / f"{post['slug']}.svg", svg)


def resolve_cover_image(post: dict, page: str) -> dict[str, str]:
    cover_image = post.get("cover_image")
    if cover_image and cover_image.get("url"):
        return {
            "src": cover_image["url"],
            "alt": cover_image.get("alt") or post.get("title", "Imagen editorial"),
        }
    prefix = cover_prefix(page)
    return {
        "src": f"{prefix}assets/covers/{post['slug']}.svg",
        "alt": post.get("title", "Imagen editorial"),
    }


def header(brand: dict, prefix: str) -> str:
    return f"""
<header class="site-header">
  <div class="shell masthead">
    <a class="brand" href="{prefix}/">{escape(brand.get("company_name", "Consultora IA"))}</a>
    <nav class="nav">
      <a href="{prefix}/">Inicio</a>
      <a href="{prefix}/blog/">Blog</a>
    </nav>
  </div>
</header>
""".strip()


def footer(brand: dict) -> str:
    year = datetime.now(timezone.utc).year
    return f"""
<footer class="site-footer">
  <div class="shell">
    <p>{escape(brand.get("company_name", "Consultora IA"))} (c) {year}. Contenido automatizado para posicionamiento orgánico.</p>
  </div>
</footer>
""".strip()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def escape(value: str) -> str:
    return html.escape(value or "")


def format_date(value: str | None) -> str:
    if not value:
        return "Sin fecha"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return value


def reading_time(post: dict) -> int:
    text = re.sub(r"<[^>]+>", " ", post.get("article_html", ""))
    words = [item for item in text.split() if item]
    return max(4, round(len(words) / 180))


def wrap_text(value: str, width: int, max_lines: int) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        proposal = f"{current} {word}".strip()
        if len(proposal) <= width:
            current = proposal
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def theme_palette(theme_name: str) -> dict[str, str]:
    themes = {
        "signal": {"start": "#143d59", "end": "#1f7a8c", "paper": "#f4e8c1", "ink": "#1b1b18"},
        "risk": {"start": "#3f0d12", "end": "#a71d31", "paper": "#ffd9c7", "ink": "#221712"},
        "growth": {"start": "#0f5132", "end": "#2d6a4f", "paper": "#f1f7ed", "ink": "#122219"},
        "systems": {"start": "#1b1f3b", "end": "#4a4e69", "paper": "#f2e9e4", "ink": "#15131a"},
    }
    key = (theme_name or "").lower()
    if "riesgo" in key or "risk" in key:
        return themes["risk"]
    if "growth" in key or "ventas" in key:
        return themes["growth"]
    if "crm" in key or "erp" in key or "system" in key:
        return themes["systems"]
    return themes["signal"]


def link_for_card(post: dict, page: str) -> str:
    if page == "blog":
        return f"./{post['slug']}.html"
    return f"./blog/{post['slug']}.html"


def cover_prefix(page: str) -> str:
    return "../" if page in {"blog", "post"} else "./"


if __name__ == "__main__":
    build_site()
