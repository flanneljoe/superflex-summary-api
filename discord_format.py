AMBER = 0xE8A33D

MAX_EMBEDS_PER_MESSAGE = 10
MAX_CHARS_PER_MESSAGE = 5500  # hard cap is 6000 combined; small safety margin below it


def format_summary_as_embeds(markdown: str) -> list[dict]:
    sections = markdown.split("\n## ")
    intro = sections[0].strip()
    matchups = sections[1:]

    embeds = [{"description": intro, "color": AMBER}]

    for section in matchups:
        title, _, body = section.partition("\n")
        embeds.append({"title": title.strip(), "description": body.strip(), "color": AMBER})

    return embeds


def chunk_embeds(embeds: list[dict]) -> list[list[dict]]:
    chunks = []
    current = []
    current_chars = 0

    for embed in embeds:
        embed_chars = len(embed.get("title", "")) + len(embed.get("description", ""))

        would_exceed_count = len(current) >= MAX_EMBEDS_PER_MESSAGE
        would_exceed_chars = current_chars + embed_chars > MAX_CHARS_PER_MESSAGE

        if current and (would_exceed_count or would_exceed_chars):
            chunks.append(current)
            current = []
            current_chars = 0

        current.append(embed)
        current_chars += embed_chars

    if current:
        chunks.append(current)

    return chunks