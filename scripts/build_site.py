from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from content_ops import CONFIG_DIR, DATA_DIR, DOCS_DIR, load_json


def build_site() -> None:
    brand = load_json(CONFIG_DIR / "brand.json", {})
    posts = load_json(DATA_DIR / "posts.json", [])

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "blog").mkdir(parents=True, exist_ok=True)

    for post in posts:
        render_post_page(brand, post)

    render_home_page(brand, posts)
    render_blog_index(brand, posts)
    render_robots_txt(brand)
    render_sitemap(brand, posts)


def render_home_page(brand: dict, posts: list[dict]) -> None:
    latest_cards = render_post_cards(posts[:6], page="home")
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
    <section class="hero">
      <span class="eyebrow">Contenido organico automatizado</span>
      <h1>{escape(brand.get("site_name", "Blog"))}</h1>
      <p>{escape(brand.get("homepage_intro", ""))}</p>
      <div class="cta-row">
        <a class="button button-primary" href="./blog/">Ver articulos</a>
        <a class="button button-secondary" href="./blog/">Ultima publicacion</a>
      </div>
    </section>
    <section>
      <span class="eyebrow">Posicionamiento para consultoria</span>
      <h2 class="section-title">Temas utiles para lideres que quieren automatizar con criterio</h2>
      <p class="lede">{escape(brand.get("site_tagline", ""))}</p>
      {latest_cards}
    </section>
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
    <section class="hero">
      <span class="eyebrow">Blog</span>
      <h1>Ideas accionables para automatizar mejor</h1>
      <p>{escape(brand.get("homepage_intro", ""))}</p>
    </section>
    <section>
      {cards}
    </section>
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
    linkedin_link = ""
    linkedin = post.get("linkedin", {})
    if linkedin.get("post_reference"):
        linkedin_link = (
            f'<p><strong>LinkedIn:</strong> publicado con referencia <code>{escape(linkedin["post_reference"])}</code>.</p>'
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
    <article class="article-shell">
      <span class="eyebrow">Articulo</span>
      <h1>{title}</h1>
      <div class="meta">
        <span>{format_date(post.get("published_at"))}</span>
        <span>{escape(post.get("source_name", "Curacion automatizada"))}</span>
      </div>
      <p class="lede">{description}</p>
      <div class="article-body">
        {post.get("article_html", "")}
      </div>
      <section class="sources">
        <h2>Fuentes</h2>
        <ul>{source_links}</ul>
        {linkedin_link}
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
        return '<div class="empty">Aun no hay articulos publicados. El primer run del pipeline creara la primera pieza.</div>'

    cards = []
    for post in posts:
        cards.append(
            f"""
<article class="post-card">
  <div class="meta">
    <span>{format_date(post.get("published_at"))}</span>
    <span>{escape(post.get("source_name", "Curacion automatizada"))}</span>
  </div>
  <h3><a href="{link_for_card(post, page)}">{escape(post["title"])}</a></h3>
  <p>{escape(post.get("excerpt", ""))}</p>
  <a class="button button-secondary" href="{link_for_card(post, page)}">Leer articulo</a>
</article>
""".strip()
        )
    return f'<div class="grid">{"".join(cards)}</div>'


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
    <p>{escape(brand.get("company_name", "Consultora IA"))} (c) {year}. Contenido automatizado para posicionamiento organico.</p>
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


def link_for_card(post: dict, page: str) -> str:
    if page == "blog":
        return f"./{post['slug']}.html"
    return f"./blog/{post['slug']}.html"


if __name__ == "__main__":
    build_site()
